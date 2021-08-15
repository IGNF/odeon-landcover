"""
Metrics tool to analyse the quality of a model's predictions.
Compute metrics, plot confusion matrices (cms) and ROC curves.
This tool handles binary, multi-classes and multi-labels cases.
The metrics computed are in each case :

* Binary case:
    - Accuracy
    - Precision
    - Recall
    - Specificity
    - F1 Score
    - IoU
    - Dice
    - AUC Score for ROC and PR curves
    - Expected Calibration Error (ECE)
    - Calibration Curve
    - KL Divergence

* Multi-class case:
    - 1 versus all: same metrics as the binary case for each class.
    - Macro (1 versus all then all cms stacked): same metrics as the binary case for the sum of all classes.
    - Micro : Precision, Recall, F1 Score (confusion matrix but no ROC curve).

* Multi-labels case:
    - Same as the multi-class case but without the global confusion matrix in  micro analysis.
"""
import os
import csv
import numpy as np
from odeon import LOGGER
from odeon.commons.core import BaseTool
from odeon.commons.exception import OdeonError, ErrorCodes
from metrics_factory import Metrics_Factory
from PIL import Image
from metrics import DEFAULTS_VARS


class CLI_Metrics(BaseTool):

    def __init__(self,
                 mask_path,
                 pred_path,
                 output_path,
                 type_classifier,
                 class_labels=None,
                 threshold=DEFAULTS_VARS['threshold'],
                 threshold_range=DEFAULTS_VARS['threshold_range'],
                 bit_depth=DEFAULTS_VARS['bit_depth'],
                 nb_calibration_bins=DEFAULTS_VARS['nb_calibration_bins']):

        self.mask_path = mask_path
        self.pred_path = pred_path
        self.output_path = output_path
        self.type_classifier = type_classifier
        self.class_labels = class_labels,
        self.threshold = threshold
        self.threshold_range = threshold_range
        self.bit_depth = bit_depth
        self.nb_calibration_bins = nb_calibration_bins

        self.mask_files, self.pred_files = self.get_files_from_input_paths()
        self.height, self.width, self.nbr_class = self.get_samples_shapes()
        self.masks, self.preds = self.get_array_from_files()

        self.metrics = Metrics_Factory(self.type_classifier)(masks=self.masks,
                                                             preds=self.preds,
                                                             output_path=self.output_path,
                                                             nbr_class=self.nbr_class,
                                                             class_labels=self.class_labels,
                                                             threshold=self.threshold,
                                                             threshold_range=self.threshold_range)

    def __call__(self):
        self.metrics()

    def get_files_from_input_paths(self):
        if not os.path.exists(self.mask_path):
            raise OdeonError(ErrorCodes.ERR_FILE_NOT_EXIST,
                             f"Masks folder ${self.mask_path} does not exist.")
        elif not os.path.exists(self.pred_path):
            raise OdeonError(ErrorCodes.ERR_FILE_NOT_EXIST,
                             f"Predictions folder ${self.pred_path} does not exist.")
        else:
            if os.path.isdir(self.mask_path) and os.path.isdir(self.pred_path):
                mask_files, pred_files = self.list_files_from_dir()
            else:
                LOGGER.error('ERROR: the input paths shoud point to dataset directories.')
        return mask_files, pred_files

    def read_csv_sample_file(self):
        mask_files = []
        pred_files = []

        with open(self.input_path) as csvfile:
            sample_reader = csv.reader(csvfile)
            for item in sample_reader:
                mask_files.append(item['msk_file'])
                pred_files.append(item['img_output_file'])
        return mask_files, pred_files

    def list_files_from_dir(self):
        mask_files, pred_files = [], []

        for msk, pred in zip(sorted(os.listdir(self.mask_path)), sorted(os.listdir(self.pred_path))):
            if msk == pred:
                mask_files.append(os.path.join(self.mask_path, msk))
                pred_files.append(os.path.join(self.pred_path, pred))
            else:
                LOGGER.warning(f'Problem of matching names between mask {msk} and prediction {pred}.')
        return mask_files, pred_files

    def get_samples_shapes(self):
        mask_file, pred_file = self.mask_files[0], self.pred_files[0]

        with Image.open(mask_file) as mask_img:
            mask = np.array(mask_img)
        with Image.open(pred_file) as pred_img:
            pred = np.array(pred_img)

        assert mask.shape == pred.shape, "Mask shape and prediction shape should be the same."
        if len(mask.shape) == 2:
            nbr_class = 2
        else:
            nbr_class = mask.shape[-1]
        return mask.shape[0], mask.shape[1], nbr_class

    def get_array_from_files(self):
        """[summary]
        WARNING : Need to cast masks and preds from uint8 to float to use this metrics tool!!
        Returns
        -------
        [type]
            [description]
        """
        if self.nbr_class == 2:
            masks = np.zeros([len(self.mask_files), self.height, self.width])
            preds = np.zeros([len(self.mask_files), self.height, self.width])

        else:
            masks = np.zeros([len(self.mask_files), self.height, self.width, self.nbr_class])
            preds = np.zeros([len(self.mask_files), self.height, self.width, self.nbr_class])

        for index, sample in enumerate(zip(self.mask_files, self.pred_files)):
            assert os.path.basename(sample[0]) == os.path.basename(sample[1]), \
             "Each mask should have its corresponding prediction with the same name."

            with Image.open(sample[0]) as mask_img:
                masks[index] = np.array(mask_img, dtype=np.float32)

            with Image.open(sample[1]) as pred_img:
                preds[index] = np.array(pred_img, dtype=np.float32)
        return masks, preds


if __name__ == '__main__':
    img_path = '/home/SPeillet/OCSGE/data/metrics/img'
    mask_path = '/home/SPeillet/OCSGE/data/metrics/pred_soft/binary_case/msk'
    pred_path = '/home/SPeillet/OCSGE/data/metrics/pred_soft/binary_case/pred'
    output_path = '/home/SPeillet/OCSGE/metrics.html'
    metrics = CLI_Metrics(mask_path, pred_path, output_path, type_classifier='Binary case')
    metrics()

