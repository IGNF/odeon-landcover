import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import auc
from metrics import Metrics, DEFAULTS_VARS
from tqdm import tqdm

FIGSIZE = (8, 6)


class Metrics_Binary(Metrics):

    def __init__(self,
                 masks,
                 preds,
                 output_path,
                 type_classifier,
                 nbr_class,
                 class_labels=None,
                 threshold=DEFAULTS_VARS['threshold'],
                 threshold_range=DEFAULTS_VARS['threshold_range'],
                 bit_depth=DEFAULTS_VARS['bit_depth'],
                 nb_calibration_bins=DEFAULTS_VARS['nb_calibration_bins'],
                 batch_size=DEFAULTS_VARS['batch_size'],
                 num_workers=DEFAULTS_VARS['num_workers']):

        super().__init__(masks=masks,
                         preds=preds,
                         output_path=output_path,
                         type_classifier=type_classifier,
                         nbr_class=nbr_class,
                         class_labels=class_labels,
                         threshold=threshold,
                         threshold_range=threshold_range,
                         bit_depth=bit_depth,
                         nb_calibration_bins=nb_calibration_bins,
                         batch_size=batch_size,
                         num_workers=num_workers)

        self.df_thresholds, self.cms, self.df_report_metrics = self.create_data_for_metrics()
        self.get_metrics_by_threshold()

    def create_data_for_metrics(self):
        df_thresholds = pd.DataFrame(index=range(len(self.threshold_range)),
                                     columns=(['threshold'] + self.metrics_names))
        df_thresholds['threshold'] = self.threshold_range
        cms = {}
        df_report_metrics = pd.DataFrame(index=['Values'], columns=self.metrics_names[:-1])
        return df_thresholds, cms, df_report_metrics

    def get_metrics_by_threshold(self):

        hist_counts = np.zeros(len(self.bins) - 1)
        bin_sums = np.zeros(len(self.bins))
        bin_true = np.zeros(len(self.bins))
        bin_total = np.zeros(len(self.bins))

        for threshold in tqdm(self.threshold_range, desc='Tresholds', leave=False):
            self.cms[threshold] = np.zeros([self.nbr_class, self.nbr_class])
            for mask, pred in zip(self.masks, self.preds):

                # Compute cm on every sample
                pred_cm = pred.copy()
                pred_cm = self.binarize(self.type_classifier, pred_cm, threshold=threshold)
                cm = self.get_confusion_matrix(mask.flatten(), pred_cm.flatten())
                self.cms[threshold] += cm

                # To calcultate info for calibrations curves only once.
                if threshold == self.threshold_range[0]:
                    pred_hist = pred.copy()
                    if not self.in_prob_range:
                        pred_hist = self.to_prob_range(pred_hist)
                    # bincounts for histogram of prediction
                    hist_counts += np.histogram(pred_hist.flatten(), bins=self.bins)[0]

                    # Indices of the bins where the predictions will be in there.
                    binids = np.digitize(pred_hist.flatten(), self.bins) - 1
                    # Bins counts of indices times the values of the predictions.
                    bin_sums += np.bincount(binids, weights=pred_hist.flatten(), minlength=len(self.bins))
                    # Bins counts of indices times the values of the masks.
                    bin_true += np.bincount(binids, weights=mask.flatten(), minlength=len(self.bins))
                    # Total number observation per bins.
                    bin_total += np.bincount(binids, minlength=len(self.bins))

            cr_metrics = self.get_metrics_from_cm(self.cms[threshold])

            for metric, metric_value in cr_metrics.items():
                self.df_thresholds.loc[self.df_thresholds['threshold'] == threshold, metric] = metric_value

        # Normalize hist_counts to put the values between 0 and 1:
        self.hist_counts = hist_counts / np.sum(hist_counts)
        nonzero = bin_total != 0  # Avoid to display null bins.
        self.prob_true = bin_true[nonzero] / bin_total[nonzero]
        self.prob_pred = bin_sums[nonzero] / bin_total[nonzero]

        self.df_report_metrics.loc['Values'] = \
            self.df_thresholds.loc[self.df_thresholds['threshold'] == self.threshold, self.metrics_names[:-1]].values

    def get_metrics_from_cm(self, cm):
        tp, fn, fp, tn = cm.ravel()
        return self.get_metrics_from_obs(tp, fn, fp, tn)

    def plot_PR_curve(self, precision, recall, name_plot='binary_pr_curve.png'):

        precision = np.array([1 if p == 0 and r == 0 else p for p, r in zip(precision, recall)])
        idx = np.argsort(recall)
        recall, precision = recall[idx], precision[idx]
        pr_auc = auc(recall, precision)

        plt.figure(figsize=FIGSIZE)
        plt.title('Precision-Recall Curve')
        plt.plot(recall, precision, label='AUC = %0.3f' % pr_auc)
        plt.plot([1, 0], [0, 1], 'r--')
        plt.ylabel('Precision')
        plt.xlabel('Recall')
        plt.legend()
        plt.grid(True)
        output_path = os.path.join(os.path.dirname(self.output_path), name_plot)
        plt.savefig(output_path)
        return output_path

    def plot_ROC_curve(self, fpr, tpr, name_plot='binary_roc_curve.png'):

        # Sorted fpr in increasing order to plot it as the abscisses values of the curve.
        # fpr, tpr = np.insert(fpr.to_numpy(), 0, 0), np.insert(tpr.to_numpy(), 0, 0)
        fpr, tpr = fpr[::-1], tpr[::-1]
        roc_auc = auc(fpr, tpr)

        plt.figure(figsize=FIGSIZE)
        plt.title('Roc Curve')
        plt.plot(fpr, tpr, label='AUC = %0.3f' % roc_auc)
        plt.plot([0, 1], [0, 1], 'r--')
        plt.ylabel('True Positive Rate')
        plt.xlabel('False Positive Rate')
        plt.legend()
        plt.grid(True)
        output_path = os.path.join(os.path.dirname(self.output_path), name_plot)
        plt.savefig(output_path)
        return output_path

    def plot_calibration_curve(self, name_plot='binary_calibration_curves.png'):

        plt.figure(figsize=(16, 8))
        plt.subplot(211)
        # Plot 1: calibration curves
        plt.plot([0, 1], [0, 1], "k:", label="Perfectly calibrated")
        plt.plot(self.prob_true, self.prob_pred, "s-", label="Class 1")
        plt.legend(loc="lower right")
        plt.title('Calibration plots  (reliability curve)')
        plt.ylabel('Fraction of positives')
        plt.xlabel('Probalities')

        plt.subplot(212)
        # Plot 2: Hist of predictions distributions
        plt.hist(self.hist_counts, histtype="step", bins=self.bins, label="Class 1", lw=2)
        plt.ylabel('Count')
        plt.xlabel('Mean predicted value')
        plt.legend(loc="upper center")
        output_path = os.path.join(os.path.dirname(self.output_path), name_plot)
        plt.savefig(output_path)
        return output_path
