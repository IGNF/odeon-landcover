"""
Class to manage metrics in the multiclass case.
Will generate the micro, macro and class strategies and calculate for each of them the associated metrics.
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import auc
from odeon.commons.metric.metrics import Metrics, DEFAULTS_VARS
from tqdm import tqdm
from cycler import cycler


class Metrics_Multiclass(Metrics):

    def __init__(self,
                 dataset,
                 output_path,
                 type_classifier,
                 in_prob_range,
                 class_labels=None,
                 output_type=DEFAULTS_VARS['output_type'],
                 weights=DEFAULTS_VARS['weights'],
                 threshold=DEFAULTS_VARS['threshold'],
                 n_thresholds=DEFAULTS_VARS['n_thresholds'],
                 bit_depth=DEFAULTS_VARS['bit_depth'],
                 bins=DEFAULTS_VARS['bins'],
                 n_bins=DEFAULTS_VARS['n_bins'],
                 get_normalize=DEFAULTS_VARS['get_normalize'],
                 get_metrics_per_patch=DEFAULTS_VARS['get_metrics_per_patch'],
                 get_ROC_PR_curves=DEFAULTS_VARS['get_ROC_PR_curves'],
                 get_calibration_curves=DEFAULTS_VARS['get_calibration_curves'],
                 get_hists_per_metrics=DEFAULTS_VARS['get_hists_per_metrics']):
        """
        Init function.
        Initialize the class attributes and create the dataframes to store the metrics for each strategy.
        Scan the dataset, by threshold (for ROC and PR curves in per class strategy), by classes and
        finally by sample to compute confusion matrices (cms) and metrics.
        Once the metrics and cms are computed they are exported in an output file that can have a form json,
        markdown or html. Optionally the tool can output metrics per patch and return the result as a csv file.

        Parameters
        ----------
        dataset : MetricsDataset
            Dataset from odeon.nn.datasets which contains the masks and the predictions.
        output_path : str
            Path where the report/output data will be created.
        type_classifier : str
            String allowing to know if the classifier is of type binary or multiclass.
            Here the classfier type should be 'multiclass'.
        in_prob_range : boolean,
            Boolean to be set to true if the values in the predictions passed as inputs are between 0 and 1.
            If not, set the parameter to false so that the tool modifies the values to be normalized between 0 and 1.
        output_type : str, optional
            Desired format for the output file. Could be json, md or html.
            A report will be created if the output type is html or md.
            If the output type is json, all the data will be exported in a dict in order
            to be easily reusable, by default html.
        class_labels : list of str, optional
            Label for each class in the dataset.
            If None the labels of the classes will be of type: class 1, class 2, etc .., by default None
        weights : list of number, optional
            List of weights to balance the metrics.
            Used for the macro matrix and the mean metrics, by default None.
        threshold : float, optional
            Value between 0 and 1 that will be used as threshold to binarize data if they are soft.
            Use for macro, micro cms and metrics for all strategies, by default 0.5.
        n_thresholds : int, optional
            Number of thresholds used in the computation of ROC and PR, by default 10.
        bit_depth : str, optional
            The number of bits used to represent each pixel in a mask/prediction, by default '8 bits'
        bins: list of float, optional
            List of bins used for the creation of histograms.
        n_bins : int, optional
            Number of bins used in the construction of calibration curves, by default 10.
        get_normalize : bool, optional
            Boolean to know if the user wants to generate confusion matrices with normalized values, by default True
        get_metrics_per_patch : bool, optional
            Boolean to know if the user wants to compute metrics per patch and export them in a csv file.
            Metrics will be also computed if the parameter get_hists_per_metrics is True but a csv file
            won't be created, by default True
        get_ROC_PR_curves : bool, optional
            Boolean to know if the user wants to generate ROC and PR curves, by default True
        get_calibration_curves : bool, optional
            Boolean to know if the user wants to generate calibration curves, by default True
        get_hists_per_metrics : bool, optional
            Boolean to know if the user wants to generate histogram for each metric.
            Histograms created using the parameter threshold, by default True.
        """

        super().__init__(dataset=dataset,
                         output_path=output_path,
                         type_classifier=type_classifier,
                         in_prob_range=in_prob_range,
                         class_labels=class_labels,
                         output_type=output_type,
                         weights=weights,
                         threshold=threshold,

                         n_thresholds=n_thresholds,
                         bit_depth=bit_depth,
                         bins=bins,
                         n_bins=n_bins,
                         get_normalize=get_normalize,
                         get_metrics_per_patch=get_metrics_per_patch,
                         get_ROC_PR_curves=get_ROC_PR_curves,
                         get_calibration_curves=get_calibration_curves,
                         get_hists_per_metrics=get_hists_per_metrics)

        self.df_report_classes, self.df_report_micro, self.df_report_macro = self.create_data_for_metrics()

        # Dataframe for metrics per patch.
        if self.get_metrics_per_patch:
            self.header = ['name_file'] + \
                        ['OA', 'micro_IoU'] + \
                        ['macro_' + name_column for name_column in ['Precision', 'Recall', 'F1-Score', 'IoU']] + \
                        ['mean_' + name_column for name_column in self.metrics_names[:-1]] + \
                        ['_'.join(class_i.split(' ')) + '_' + name_column for class_i in self.class_labels
                         for name_column in self.metrics_names[:-1]]
            self.df_dataset = pd.DataFrame(index=range(len(self.dataset)), columns=self.header)

    def run(self):
        """
        Run the methods to compute metrics.
        """
        # Computed confusion matrix for each sample and sum the total in one micro cm.
        self.cm_macro = self.scan_dataset()

        # Get metrics for each strategy and cms macro from the micro cm.
        self.metrics_by_class, self.metrics_micro, self.cms_classes, self.cm_micro = \
            self.get_metrics_from_cm(self.cm_macro)

        # Put the calculated metrics in dataframes for reports and also computed mean metrics.
        self.metrics_to_df_reports()

        # Create a csv to export the computed metrics per patch.
        if self.get_metrics_per_patch:
            self.export_metrics_per_patch_csv()

    def create_data_for_metrics(self):
        """
        Create dataframes to store metrics for each strategy.

        Returns
        -------
        Tuple of pd.DataFrame
            Dataframes to store metrics for each strategy.
        """
        df_report_classes = pd.DataFrame(index=[class_name for class_name in self.class_labels],
                                         columns=self.metrics_names[:-1])
        df_report_micro = pd.DataFrame(index=['Values'],
                                       columns=['OA', 'IoU'])
        if self.weighted:
            df_report_macro = pd.DataFrame(index=['Average', 'Weighted avg', 'User weighted avg'],
                                           columns=['Precision', 'Recall', 'F1-Score', 'IoU'])
        else:
            df_report_macro = pd.DataFrame(index=['Average', 'Weighted avg'],
                                           columns=['Precision', 'Recall', 'F1-Score', 'IoU'])
        return df_report_classes, df_report_micro, df_report_macro

    def scan_dataset(self):
        """
        Function allowing to make a pass on the dataset in order to obtain micro confusion
        matrices by sample according to given thresholds. For each threshold, then the cms
        are added together to make only one micro cm by threshold. The function only return the
        micro cm with a threshold equal to the parameter threshold given as input.

        Returns
        -------
        np.array
            Confusion matrix for micro strategy.
        """
        cm_macro = np.zeros([self.nbr_class, self.nbr_class])
        # Dict and dataframe to store data for ROC and PR curves.
        self.cms_one_class = pd.DataFrame(index=self.threshold_range, columns=self.class_labels, dtype=object)
        self.cms_one_class = self.cms_one_class.applymap(lambda x: np.zeros([2, 2]))

        # Dicts to store info for calibrations curves.
        self.dict_prob_true, self.dict_prob_pred = {}, {}
        self.dict_hist_counts = {class_i: np.zeros(len(self.bins) - 1) for class_i in self.class_labels}
        self.dict_bin_sums = {class_i: np.zeros(len(self.bins)) for class_i in self.class_labels}
        self.dict_bin_true = {class_i: np.zeros(len(self.bins)) for class_i in self.class_labels}
        self.dict_bin_total = {class_i: np.zeros(len(self.bins)) for class_i in self.class_labels}

        self.counts_sample_per_class = {class_i: 0 for class_i in self.class_labels}

        for dataset_index, sample in enumerate(tqdm(self.dataset, desc='Metrics processing time', leave=True)):
            mask, pred, name_file = sample['mask'], sample['pred'], sample['name_file']
            for i, class_i in enumerate(self.class_labels):

                for threshold in self.threshold_range:
                    class_mask = mask[:, :, i]
                    class_pred = pred[:, :, i]

                    self.counts_sample_per_class[class_i] += np.count_nonzero(class_mask)

                    bin_pred = self.binarize('binary', class_pred, threshold=threshold)
                    cr_cm = self.get_confusion_matrix(class_mask.flatten(), bin_pred.flatten(),
                                                      nbr_class=2, revert_order=True)
                    self.cms_one_class.loc[threshold, class_i] += cr_cm

                    # To compute only once data for cm micro.
                    if threshold == self.threshold and i == 0:
                        # Compute cm micro for every sample and stack the results to a total micro cm.
                        # Here binarization with an argmax.
                        mask_macro, pred_macro = self.binarize(self.type_classifier, pred, mask=mask)
                        cm = self.get_confusion_matrix(mask_macro.flatten(), pred_macro.flatten(), revert_order=False)
                        cm_macro += cm

                        # Compute metrics per patch
                        if self.get_metrics_per_patch:
                            # Get a cm for every sample
                            metrics_by_class, metrics_micro,  _, _ = self.get_metrics_from_cm(cm)
                            self.df_dataset.loc[dataset_index, 'name_file'] = name_file
                            # in micro, recall = precision = f1-score = oa
                            self.df_dataset.loc[dataset_index, 'OA'] = metrics_micro['Precision']
                            self.df_dataset.loc[dataset_index, 'micro_IoU'] = metrics_micro['IoU']

                            # Per classes patch metrics
                            for label in self.class_labels:
                                for name_column in self.metrics_names[:-1]:
                                    self.df_dataset.loc[dataset_index, '_'.join(label.split(' ')) + '_' + name_column] \
                                        = metrics_by_class[label][name_column]

                            # Mean metrics per sample
                            for metric in self.metrics_names[:-1]:
                                mean_metric = 0
                                for class_name, weight in zip(self.class_labels, self.weights):
                                    mean_metric += \
                                        weight * self.df_dataset.loc[dataset_index, '_'.join(class_name.split(' ')) +
                                                                                    '_' + metric]
                                self.df_dataset.loc[dataset_index, 'mean_' + metric] = mean_metric / self.nbr_class
                                if metric in ['Precision', 'Recall', 'F1-Score', 'IoU']:
                                    self.df_dataset.loc[dataset_index, 'macro_' + metric] = mean_metric / self.nbr_class

                    # To compute only once per class calibration curves.
                    if threshold == self.threshold:
                        pred_hist = pred[:, :, i]
                        mask_hist = mask[:, :, i]

                        if not self.in_prob_range:
                            pred_hist = self.to_prob_range(pred_hist)

                        # Bincounts for histogram of prediction
                        self.dict_hist_counts[class_i] += np.histogram(pred_hist.flatten(), bins=self.bins)[0]
                        # Indices of the bins where the predictions will be in there.
                        binids = np.digitize(pred_hist.flatten(), self.bins) - 1
                        # Bins counts of indices times the values of the predictions.
                        self.dict_bin_sums[class_i] += np.bincount(binids, weights=pred_hist.flatten(),
                                                                   minlength=len(self.bins))
                        # Bins counts of indices times the values of the masks.
                        self.dict_bin_true[class_i] += np.bincount(binids, weights=mask_hist.flatten(),
                                                                   minlength=len(self.bins))
                        # Total number observation per bins.
                        self.dict_bin_total[class_i] += np.bincount(binids, minlength=len(self.bins))

        self.cms_one_class = \
            self.cms_one_class.applymap(lambda cm_one_class: self.get_metrics_from_obs(cm_one_class[0][0],
                                                                                       cm_one_class[0][1],
                                                                                       cm_one_class[1][0],
                                                                                       cm_one_class[1][1]))
        self.vect_classes = {}
        for class_j in self.class_labels:
            nonzero = self.dict_bin_total[class_j] != 0  # Avoid to display null bins.
            # The proportion of samples whose class is the positive class, in each bin (fraction of positives).
            prob_true = self.dict_bin_true[class_j][nonzero] / self.dict_bin_total[class_j][nonzero]
            # The mean predicted probability in each bin.
            prob_pred = self.dict_bin_sums[class_j][nonzero] / self.dict_bin_total[class_j][nonzero]
            self.dict_prob_true[class_j] = prob_true
            self.dict_prob_pred[class_j] = prob_pred

            vects = {'Recall': [], 'FPR': [], 'Precision': []}
            for metrics_raw in self.cms_one_class.loc[:, class_j]:
                vects['Recall'].append(metrics_raw['Recall'])
                vects['FPR'].append(metrics_raw['FPR'])
                vects['Precision'].append(metrics_raw['Precision'])
            self.vect_classes[class_j] = vects
        return cm_macro

    def get_obs_by_class_from_cm(self, cm):
        """
        Function to get the metrics for each class from a confusion matrix.

        Parameters
        ----------
        cm : np.array
            Input confusion matrix.

        Returns
        -------
        dict
            Dict with metrics for each class.
            The keys of th dict will be the labels of the classes.
        """
        obs_by_class = {}
        for i, class_i in enumerate(self.class_labels):
            obs_by_class[class_i] = {'tp': cm[i, i],
                                     'fn': np.sum(cm[i, :]) - cm[i, i],
                                     'fp': np.sum(cm[:, i]) - cm[i, i],
                                     'tn': np.sum(cm) - np.sum(cm[i, :]) - np.sum(cm[:, i]) + cm[i, i]}
        return obs_by_class

    def get_metrics_from_cm(self, cm_macro):
        """
        Function to get metrics from a confusion matrix.

        Parameters
        ----------
        cm_micro : np.array
            Confusion matrix in micro strategy.
        Returns
        -------
        (dict, dict, dict, np.array, np.array)
            Metrics (macro, micro, per class) and cms (macro, per class).
        """
        obs_by_class = self.get_obs_by_class_from_cm(cm_macro)
        cms_classes = np.zeros([self.nbr_class, 2, 2])

        metrics_by_class = {}
        for i, class_i in enumerate(self.class_labels):
            cms_classes[i] = np.array([[obs_by_class[class_i]['tp'], obs_by_class[class_i]['fn']],
                                       [obs_by_class[class_i]['fp'], obs_by_class[class_i]['tn']]])
            metrics_by_class[class_i] = self.get_metrics_from_obs(obs_by_class[class_i]['tp'],
                                                                  obs_by_class[class_i]['fn'],
                                                                  obs_by_class[class_i]['fp'],
                                                                  obs_by_class[class_i]['tn'])

        # If weights are used, the sum of the confusion matrices of each class weighted by the input weights.
        # If not, the confusions matrices of classes will directly added together.
        if self.weighted:
            cm_micro = np.zeros([2, 2])
            for k, weight in zip(range(self.nbr_class), self.weights):
                cm_micro += cms_classes[k] * weight
        else:
            cm_micro = np.sum(cms_classes, axis=0)

        metrics_micro = self.get_metrics_from_obs(cm_micro[0][0],
                                                  cm_micro[0][1],
                                                  cm_micro[1][0],
                                                  cm_micro[1][1])

        return metrics_by_class, metrics_micro, cms_classes, cm_micro

    def metrics_to_df_reports(self):
        """
        Put the calculated metrics in dataframes for reports and also computed mean metrics.
        """
        for class_i in self.class_labels:
            self.df_report_classes.loc[class_i] = list(self.metrics_by_class[class_i].values())[:-1]
        self.df_report_classes.loc['Overall'] = self.df_report_classes.mean()

        self.df_report_macro.loc['Average'] = [self.df_report_classes.loc['Overall', 'Precision'],
                                               self.df_report_classes.loc['Overall', 'Recall'],
                                               self.df_report_classes.loc['Overall', 'F1-Score'],
                                               self.df_report_classes.loc['Overall', 'IoU']]

        total_positive_obs = sum([value for _, value in self.counts_sample_per_class.items()])
        for metric in ['Precision', 'Recall', 'F1-Score', 'IoU']:
            weighted_avg = 0
            user_weighted_avg = 0
            for i, class_i in enumerate(self.class_labels):
                weighted_avg += self.df_report_classes.loc[class_i, metric] * self.counts_sample_per_class[class_i]

                if self.weighted:
                    user_weighted_avg += self.df_report_classes.loc[class_i, metric] * self.weights[i]

            self.df_report_macro.loc['Weighted avg', metric] = np.round(weighted_avg / total_positive_obs, decimals=2)

            if self.weighted:
                self.df_report_macro.loc['User weighted avg', metric] = np.round(user_weighted_avg / self.nbr_class,
                                                                                 decimals=2)

        # In micro : micro-F1 = micro-precision = micro-recall = accuracy
        self.df_report_micro.loc['Values'] = [self.metrics_micro['Precision'],
                                              self.metrics_micro['IoU']]

    def plot_ROC_PR_per_class(self, name_plot='multiclass_roc_pr_curves.png'):
        """
        Plot (html/md output type) or export (json type) data on ROC and PR curves.
        For ROC curve, points (0, 0) and (1, 1) are added to data in order to have a curve
        which begin at the origin and finish in the top right of the image.
        Same thing for PR curve but with the points (0, 1) and (1, 0).

        Parameters
        ----------
        name_plot : str, optional
            Desired name to give to the output image, by default 'multiclass_roc_pr_curves.png'

        Returns
        -------
        str
            Output path where an image with the plot will be created.
        """
        if self.output_type == 'json':
            self.dict_export['PR ROC info'] = self.vect_classes
        else:
            plt.figure(figsize=(16, 8))
            plt.subplot(121)
            for class_i in self.class_labels:
                fpr = np.array(self.vect_classes[class_i]['FPR'])
                tpr = np.array(self.vect_classes[class_i]['Recall'])
                fpr, tpr = fpr[::-1], tpr[::-1]
                fpr, tpr = np.insert(fpr, 0, 0), np.insert(tpr, 0, 0)
                fpr, tpr = np.append(fpr, 1), np.append(tpr, 1)
                roc_auc = auc(fpr, tpr)
                plt.plot(fpr, tpr, label=f'{class_i} AUC = {round(roc_auc, 3)}')
            plt.plot([0, 1], [0, 1], 'r--')
            plt.ylabel('True Positive Rate')
            plt.xlabel('False Positive Rate')
            plt.title('Roc Curves')
            plt.legend(loc='lower right')
            plt.grid(True)

            plt.subplot(122)
            for class_i in self.class_labels:
                precision = np.array(self.vect_classes[class_i]['Precision'])
                recall = np.array(self.vect_classes[class_i]['Recall'])
                precision = np.array([1 if p == 0 and r == 0 else p for p, r in zip(precision, recall)])
                idx = np.argsort(recall)
                recall, precision = recall[idx], precision[idx]
                recall, precision = np.insert(recall, 0, 0), np.insert(precision, 0, 1)
                recall, precision = np.append(recall, 1), np.append(precision, 0)
                pr_auc = auc(recall, precision)
                plt.plot(recall, precision, label=f'{class_i} AUC = {round(pr_auc, 3)}')
            plt.plot([1, 0], [0, 1], 'r--')
            plt.title('Precision-Recall Curve')
            plt.ylabel('Precision')
            plt.xlabel('Recall')
            plt.legend(loc='lower left')
            plt.grid(True)
            plt.tight_layout(pad=3)
            output_path = os.path.join(self.output_path, name_plot)
            plt.savefig(output_path)
            return output_path

    def plot_calibration_curve(self, name_plot='multiclass_calibration_curves.png'):
        """
        Plot or export data on calibration curves.
        Plot for output type html and md, export the data in a dict for json.

        Parameters
        ----------
        name_plot : str, optional
            Name to give to the output plot, by default 'multiclass_calibration_curves.png'

        Returns
        -------
        str
            Output path where an image with the plot will be created.
        """
        # Normalize dict_hist_counts to put the values between 0 and 1:
        total_pixel = np.sum(self.dict_hist_counts[self.class_labels[0]])
        self.dict_hist_counts = {key: value / total_pixel for key, value in self.dict_hist_counts.items()}

        if self.output_type == 'json':
            dict_prob_true, dict_prob_pred, dict_hist_counts = {}, {}, {}
            for class_i in self.class_labels:
                dict_prob_true[class_i] = self.dict_prob_true[class_i].tolist()
                dict_prob_pred[class_i] = self.dict_prob_pred[class_i].tolist()
                dict_hist_counts[class_i] = self.dict_hist_counts[class_i].tolist()

            self.dict_export['calibration curve'] = {'prob_true': dict_prob_true,
                                                     'prob_pred': dict_prob_pred,
                                                     'hist_counts': dict_hist_counts}
        else:
            plt.figure(figsize=(16, 8))
            # Plot 1: calibration curves
            plt.subplot(211)
            plt.plot([0, 1], [0, 1], "k:", label="Perfectly calibrated")
            for class_i in self.class_labels:
                plt.plot(self.dict_prob_true[class_i], self.dict_prob_pred[class_i], "s-", label=class_i)
            plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
            plt.title('Calibration plots (reliability curve)')
            plt.ylabel('Fraction of positives')
            plt.xlabel('Probalities')

            # Plot 2: Hist of predictions distributions
            plt.subplot(212)
            for class_i in self.class_labels:
                plt.hist(self.bins[:-1], weights=self.dict_hist_counts[class_i],
                         bins=self.bins, histtype="step", label=class_i, lw=2)
            plt.xticks(self.bins_xticks, self.bins_xticks)
            plt.ylabel('Count')
            plt.xlabel('Mean predicted value')
            plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
            plt.tight_layout(pad=3)

            output_path = os.path.join(self.output_path, name_plot)
            plt.savefig(output_path)
            return output_path

    def plot_hists(self, list_metrics, n_cols=3, size_col=5, size_row=4, bins=None, name_plot=None):
        """
        Plot metrics histograms.

        Parameters
        ----------
        list_metrics : list
            Name of the metrics to plot.
        n_cols : int, optional
            number of columns in the figure, by default 3
        size_col : int, optional
            size of a column in the figure, by default 5
        size_row : int, optional
            size of a row in the figure, by default 4
        bins : list of int, optional
            Bins used for bins counts for the creation of the histograms, by default None
        name_plot : str, optional
            Name to give to the output plot, by default 'multiclass_hists_metrics.png'

        Returns
        -------
        str
            Output path where an image with the plot will be created.
        """
        cmap_colors = [plt.get_cmap('turbo')(1. * i/7) for i in range(7)][1:]
        colors = cycler(color=cmap_colors)
        plt.rc('axes', prop_cycle=colors)

        n_plot = len(list_metrics)
        n_rows = ((n_plot - 1) // n_cols) + 1
        plt.figure(figsize=(size_col * n_cols, size_row * n_rows))
        for i, plot_prop in enumerate(zip(list_metrics, colors)):
            metric, c = plot_prop[0], plot_prop[1]["color"]
            values = self.hists_metrics[metric]
            plt.subplot(n_rows, n_cols, i+1)
            plt.bar(range(len(values)), values, width=0.8, linewidth=2, capsize=20, color=c)
            if self.n_bins <= 20:
                plt.xticks(range(len(self.bins_xticks)), self.bins_xticks, rotation=-35)
            plt.title(f"{' '.join(metric.split('_'))}", fontsize=13)
            plt.xlabel("Values bins")
            plt.grid()
            plt.ylabel("Samples count")

        plt.tight_layout(pad=3)
        output_path = os.path.join(self.output_path, name_plot)
        plt.savefig(output_path)
        return output_path

    def plot_dataset_metrics_histograms(self):
        """
        Plot (html/md output type) or export (json type) data on the metrics histograms.

        Parameters
        ----------
        name_plot : str, optional
            Name to give to the output plot, by default 'multiclass_hists_metrics.png'

        Returns
        -------
        str
            Output path where an image with the plot will be created.
        """
        self.hists_metrics = {}
        for metric in self.header[1:]:
            self.hists_metrics[metric] = np.histogram(list(self.df_dataset.loc[:, metric]), bins=self.bins)[0].tolist()

        if self.output_type == 'json':
            self.dict_export['df_dataset'] = self.df_dataset.to_dict()
            self.dict_export['hists metrics'] = self.hists_metrics
        else:
            output_paths = {}
            # 0 is name_file and and there 2 metrics in micro => 1:(1+2)
            start = 1
            end = start + self.nbr_metrics_micro
            output_paths['micro'] = self.plot_hists(self.header[start:end],
                                                    n_cols=2, size_col=8,
                                                    size_row=5, bins=self.bins,
                                                    name_plot='hists_micro.png')
            # there 4 metrics in macro => :(2+4)
            start = end
            end = start + self.nbr_metrics_macro
            output_paths['macro'] = self.plot_hists(self.header[start:end], n_cols=4, size_col=7,
                                                    size_row=6, bins=self.bins,
                                                    name_plot='hists_macro.png')
            # Again there 6 metrics in means 6:(6 + 6)
            start = end
            end = start + self.nbr_metrics_per_class
            output_paths['means'] = self.plot_hists(self.header[start:end], bins=self.bins, name_plot='hists_means.png')

            header_index = end
            for class_i in self.class_labels:
                header_next_index = header_index + self.nbr_metrics_per_class
                output_paths[class_i] = self.plot_hists(self.header[header_index:header_next_index],
                                                        bins=self.bins,
                                                        name_plot='hists_'+'_'.join(class_i.split(' '))+'.png')
                header_index = header_next_index
            return output_paths

    def export_metrics_per_patch_csv(self):
        """
            Export the metrics per patch in a csv file.
        """
        path_csv = os.path.join(self.output_path, 'metrics_per_patch.csv')
        self.df_dataset.to_csv(path_csv, index=False)