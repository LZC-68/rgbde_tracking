""" Train loop boilerplate code

    Uses preinstantiated data loaders, network, loss and optimizer to train a model.

    - Supports multiple inputs
    - Supports multiple outputs

"""
from pytorch_toolbox.utils import AverageMeter
import time
import torch
from tqdm import tqdm
import numpy as np
import os


class TrainLoop:

    def __init__(self, model, train_data_loader, valid_data_loader, optimizer, backend):
        """
        See examples/classification/train.py for usage

        :param model:               Any NetworkBase (in pytorch_toolbox.network) (it is the network model to train)
        :param train_data_loader:   Any torch dataloader for training data
        :param valid_data_loader:   Any torch dataloader for validation data
        :param optimizer:           Any torch optimizer
        :param backend:             cuda | cpu
        """
        self.train_data = train_data_loader
        self.valid_data = valid_data_loader
        self.optim = optimizer
        self.backend = backend
        self.model = model

        self.callbacks = []

        if backend == "cuda":
            self.model = self.model.cuda()

    @staticmethod
    def setup_loaded_data(data, target, backend):
        """
        Will make sure that the targets are formated as list in the right backend
        :param data:
        :param target:
        :param backend: cuda | cpu
        :return:
        """
        if not isinstance(data, list):
            data = [data]

        if not isinstance(target, list):
            target = [target]

        if backend == "cuda":
            for i in range(len(data)):
                data[i] = data[i].cuda()
            for i in range(len(target)):
                target[i] = target[i].cuda()
        else:
            for i in range(len(data)):
                data[i] = data[i].cpu()
            for i in range(len(target)):
                target[i] = target[i].cpu()
        return data, target

    @staticmethod
    def to_autograd(data, target, isvalid=True):
        """
        Converts data and target to autograd Variable
        :param data:
        :param target:
        :return:
        """
        target_var = []
        data_var = []
        for i in range(len(data)):
            data_var.append(torch.autograd.Variable(data[i], volatile=isvalid))
        for i in range(len(target)):
            target_var.append(torch.autograd.Variable(target[i], volatile=isvalid))
        return data_var, target_var

    def predict(self, data_variable):
        """
        compute prediction
        :param data_variable: tuple containing the network's input data
        :return:
        """
        y_pred = self.model(*data_variable)
        if not isinstance(y_pred, tuple):
            y_pred = (y_pred,)
        return y_pred

    def add_callback(self, func):
        """
        take a callback that will be called during the training process. See pytorch_toolbox.loop_callback_base

        :param func:
        :return:
        """
        if isinstance(func, list):
            for cb in func:
                self.callbacks.append(cb)
        else:
            self.callbacks.append(func)

    def train(self):
        """
        Minibatch loop for training. Will iterate through the whole dataset and backprop for every minibatch

        It will keep an average of the computed losses and every score obtained with the user's callbacks.

        The information is displayed on the console

        :return: averageloss, [averagescore1, averagescore2, ...]
        """
        batch_time = AverageMeter()
        data_time = AverageMeter()
        losses = AverageMeter()
        end = time.time()

        self.model.train()

        for i, (data, target) in tqdm(enumerate(self.train_data), total=len(self.train_data)):
            data_time.update(time.time() - end)
            data, target = self.setup_loaded_data(data, target, self.backend)
            data_var, target_var = self.to_autograd(data, target, isvalid=False)
            y_pred = self.predict(data_var)
            loss = self.model.loss(y_pred, target_var)
            losses.update(loss.data[0], data[0].size(0))

            for i, callback in enumerate(self.callbacks):
                callback.batch(y_pred, data, target, isvalid=False)

            self.optim.zero_grad()
            loss.backward()
            self.optim.step()

            batch_time.update(time.time() - end)
            end = time.time()

        for i, callback in enumerate(self.callbacks):
            callback.epoch(losses.avg, data_time.avg, batch_time.avg, isvalid=False)

        return losses

    def validate(self):
        """
        Validation loop (refer to train())

        Only difference is that there is no backpropagation..

        #TODO: It repeats mostly train()'s code...

        :return:
        """
        batch_time = AverageMeter()
        data_time = AverageMeter()
        losses = AverageMeter()

        self.model.eval()

        end = time.time()
        for i, (data, target) in enumerate(self.valid_data):
            data_time.update(time.time() - end)
            data, target = self.setup_loaded_data(data, target, self.backend)
            data_var, target_var = self.to_autograd(data, target, isvalid=True)
            y_pred = self.predict(data_var)
            loss = self.model.loss(y_pred, target_var)
            losses.update(loss.data[0], data[0].size(0))

            for i, callback in enumerate(self.callbacks):
                callback.batch(y_pred, data, target, isvalid=True)

            batch_time.update(time.time() - end)
            end = time.time()

        for i, callback in enumerate(self.callbacks):
            callback.epoch(losses.avg, data_time.avg, batch_time.avg, isvalid=True)

        return losses

    @staticmethod
    def load_checkpoint(path="", filename='checkpoint*.pth.tar'):
        """
        Helper function to load models's parameters
        :param state:   dict with metadata and models's weight
        :param path:    load path
        :param filename:string
        :return:
        """
        file_path = os.path.join(path, filename)
        print("Loading model...")
        state = torch.load(file_path)
        dict = state['state_dict']
        best_prec1 = state['best_prec1']
        epoch = state['epoch'] - 1
        return dict, best_prec1, epoch

    def loop(self, epochs_qty, output_path,
             load_best_checkpoint=False,
             load_last_checkpoint=False,
             save_best_checkpoint=True,
             save_last_checkpoint=True,
             save_all_checkpoints=True):
        """
        Training loop for n epoch.
        todo : Use callback instead of hardcoded savetxt to leave the user choise on results handling
        :param load_best_checkpoint:  If true, will check for model_best.pth.tar in output path and load it.
        :param save_best_checkpoint:  If true, will save model_best.pth.tar in output path.
        :param save_all_checkpoints:  If true, will save all checkpoints as checkpoint<epoch>.pth.tar in output path.
        :param epochs_qty:            Number of epoch to train
        :param output_path:           Path to save the model and log data
        :return:
        """
        best_prec1 = float('Inf')
        epoch_start = 0

        assert not(load_best_checkpoint and load_last_checkpoint), 'Choose to load only one model: last or best'
        if load_best_checkpoint or load_last_checkpoint:
            model_name = 'model_best.pth.tar' if load_best_checkpoint else 'model_last.pth.tar'
            if os.path.exists(os.path.join(output_path, model_name)):
                dict, best_prec1, epoch_best = self.load_checkpoint(output_path, model_name)
                self.model.load_state_dict(dict)
                # also get back the last i_epoch, won't start from 0 again
                epoch_start = epoch_best + 1
            else:
                raise RuntimeError("Can't load model {}".format(os.path.join(output_path, model_name)))

        for epoch in range(epoch_start, epochs_qty):
            print("-" * 20)
            print(" * EPOCH : {}".format(epoch))

            self.train()
            val_loss = self.validate()

            validation_loss_average = val_loss.avg

            # remember best loss and save checkpoint
            is_best = validation_loss_average < best_prec1
            best_prec1 = min(validation_loss_average, best_prec1)
            checkpoint_data = {'epoch': epoch, 'state_dict': self.model.state_dict(), 'best_prec1': best_prec1}
            if save_all_checkpoints:
                torch.save(checkpoint_data, os.path.join(output_path, "checkpoint{}.pth.tar".format(epoch)))
            if save_best_checkpoint and is_best:
                torch.save(checkpoint_data, os.path.join(output_path, "model_best.pth.tar"))
            if save_last_checkpoint:
                torch.save(checkpoint_data, os.path.join(output_path, "model_last.pth.tar"))

