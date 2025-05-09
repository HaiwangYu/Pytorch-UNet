#!/usr/bin/env python

import sys
import os
import math
import itertools
from optparse import OptionParser
import numpy as np

import torch
import torch.backends.cudnn as cudnn
import torch.nn as nn
from torch import optim

from unet import UNet
from uresnet import UResNet
from nestedunet import NestedUNet

from eval_util import eval_dice, eval_loss, eval_eff_pur
from utils import get_ids, split_ids, split_train_val, get_imgs_and_masks, batch
from utils import h5_utils as h5u

def print_lr(optimizer):
    for param_group in optimizer.param_groups:
        print(param_group['lr'])

def lr_exp_decay(optimizer, lr0, gamma, epoch):
    lr = lr0*math.exp(-gamma*epoch)
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr
    return optimizer

def train_net(net,
              im_tags = ['frame_loose_lf0', 'frame_mp2_roi0', 'frame_mp3_roi0'],
              ma_tags = ['frame_ductor0'],
              truth_th = 100,
              epochs=5,
              samples=10,
              batch_size=10,
              lr=0.1,
              val_percent=0.10,
              save_cp=True,
              gpu=False,
              img_scale=0.5):

    dir_checkpoint = 'checkpoints/'
    ids = list(np.arange(samples))
    iddataset = split_train_val(ids, val_percent)

    outfile_log = open(dir_checkpoint+'/log','w')

    print(iddataset['train'], file=outfile_log, flush=True)

    print('''
    Starting training:
        Epochs: {}
        Batch size: {}
        Learning rate: {}
        Training size: {}
        Validation size: {}
        Checkpoints: {}
        CUDA: {}
    '''.format(epochs, batch_size, lr, len(iddataset['train']),
               len(iddataset['val']), str(save_cp), str(gpu)), file=outfile_log, flush=True)

    N_train = len(iddataset['train'])

    optimizer = optim.SGD(net.parameters(), lr=lr, momentum=0.9, weight_decay=0.0005)
    # optimizer = optim.Adam(net.parameters(), lr=lr)
    
    criterion = nn.BCELoss()

    print('''
    im_tags: {}
    ma_tags: {}
    truth_th: {}
    '''.format(im_tags,ma_tags,truth_th), file=outfile_log, flush=True)
    outfile_loss_batch = open(dir_checkpoint+'/loss-batch.csv','w')
    outfile_loss       = open(dir_checkpoint+'/loss.csv','w')
    outfile_eval_dice  = open(dir_checkpoint+'/eval-dice.csv','w')
    outfile_eval_loss  = open(dir_checkpoint+'/eval-loss.csv','w')

    eval_labels = [
        '75-75',
        '87-85',
    ]
    eval_imgs = []
    eval_masks = []
    for label in eval_labels:
        eval_imgs.append('eval/eval-'+label+'/g4-rec-0.h5')
        eval_masks.append('eval/eval-'+label+'/g4-tru-0.h5') 
    outfile_ep = []
    for label in eval_labels:
        outfile_ep.append(open(dir_checkpoint+'/ep-'+label+'.csv','w'))
    
    epoch_start = 0
    for epoch in range(epoch_start,epoch_start+epochs):
        # scheduler = lr_exp_decay(optimizer, lr, 0.04, epoch)
        scheduler = optimizer
        
        print('epoch: {} start'.format(epoch))
        print(optimizer, file=outfile_log, flush=True)

        file_img  = 'data/cosmic-rec-0.h5'
        file_mask = 'data/cosmic-tru-0.h5'
        
        rebin = [1, 10]
        x_range = [800, 1600]
        y_range = [0, 600]
        z_scale = 4000
        
        print('''
        file_img: {}
        file_mask: {}
        '''.format(file_img, file_mask), file=outfile_log, flush=True)

        print('Starting epoch {}/{}.'.format(epoch + 1, epochs))
        net.train()

        train = zip(
          h5u.get_chw_imgs(file_img, iddataset['train'], im_tags, rebin, x_range, y_range, z_scale),
          h5u.get_masks(file_mask,   iddataset['train'], ma_tags, rebin, x_range, y_range, truth_th)
        )
        val = zip(
          h5u.get_chw_imgs(file_img, iddataset['val'],   im_tags, rebin, x_range, y_range, z_scale),
          h5u.get_masks(file_mask,   iddataset['val'],   ma_tags, rebin, x_range, y_range, truth_th)
        )
        eval_data = []
        for i in range(len(eval_imgs)):
            id_eval = [0]
            eval_data.append(
                zip(
                    h5u.get_chw_imgs(eval_imgs[i], id_eval,   im_tags, rebin, x_range, y_range, z_scale),
                    h5u.get_masks(eval_masks[i],   id_eval,   ma_tags, rebin, x_range, y_range, truth_th)
                )
            )

        epoch_loss = 0

        for i, b in enumerate(batch(train, batch_size)):
            imgs = np.array([i[0] for i in b]).astype(np.float32)
            true_masks = np.array([i[1] for i in b])

            imgs = torch.from_numpy(imgs)
            true_masks = torch.from_numpy(true_masks)

            if gpu:
                imgs = imgs.cuda()
                true_masks = true_masks.cuda()

            masks_pred = net(imgs)
            masks_probs_flat = masks_pred.view(-1)
            true_masks_flat = true_masks.view(-1)

            loss = criterion(masks_probs_flat, true_masks_flat)
            epoch_loss += loss.item()

            print('{} : {:.4f} --- loss: {:.6f}'.format(epoch, i * batch_size / N_train, loss.item()))
            print('{:.4f}, {:.6f}'.format(i * batch_size / N_train, loss.item()), file=outfile_loss_batch, flush=True)
            optimizer.zero_grad()
            loss.backward()
            # optimizer.step()
            scheduler.step()

        epoch_loss = epoch_loss / i
        print('Epoch finished ! Loss: {:.6f}'.format(epoch_loss))
        print('{:.4f}, {:.6f}'.format(epoch, epoch_loss), file=outfile_loss, flush=True)

        if save_cp:
            torch.save(net.state_dict(),
                      dir_checkpoint + 'CP{}-{}.pth'.format(epoch + 1,i+1))
            print('Checkpoint e{} saved !'.format(epoch + 1))

        if True:
            val1, val2 = itertools.tee(val, 2)
            
            val_dice = eval_dice(net, val1, gpu)
            print('Validation Dice Coeff: {:.4f}, {:.6f}'.format(epoch, val_dice))
            print('{:.4f}, {:.6f}'.format(epoch, val_dice), file=outfile_eval_dice, flush=True)

            val_loss = eval_loss(net, criterion, val2, gpu)
            print('Validation Loss: {:.4f}, {:.6f}'.format(epoch, val_loss))
            print('{:.4f}, {:.6f}'.format(epoch, val_loss), file=outfile_eval_loss, flush=True)
            
            for data, out in zip(eval_data,outfile_ep):
                ep = eval_eff_pur(net, data, 0.5, gpu)
                print('{}, {:.4f}, {:.4f}, {:.4f}, {:.4f}'.format(epoch, ep[0], ep[1], ep[2], ep[3]), file=out, flush=True)
            



def get_args():
    parser = OptionParser()
    parser.add_option('-e', '--epochs', dest='epochs', default=1, type='int',
                      help='number of epochs')
    parser.add_option('-n', '--samples', dest='samples', default=10, type='int',
                      help='number of samples')
    parser.add_option('-b', '--batch-size', dest='batchsize', default=1,
                      type='int', help='batch size')
    parser.add_option('-l', '--learning-rate', dest='lr', default=0.1,
                      type='float', help='learning rate')
    parser.add_option('-g', '--gpu', action='store_true', dest='gpu',
                      default=False, help='use cuda')
    parser.add_option('-c', '--load', dest='load',
                      default=False, help='load file model')
    parser.add_option('-s', '--scale', dest='scale', type='float',
                      default=0.5, help='downscaling factor of the images')

    (options, args) = parser.parse_args()
    return options

if __name__ == '__main__':
    args = get_args()

    torch.set_num_threads(1)

    # im_tags = ['frame_tight_lf0', 'frame_loose_lf0'] #lt
    im_tags = ['frame_loose_lf0', 'frame_mp2_roi0', 'frame_mp3_roi0']    # l23
    # im_tags = ['frame_loose_lf0', 'frame_tight_lf0', 'frame_mp2_roi0', 'frame_mp3_roi0']    # lt23
    ma_tags = ['frame_ductor0']
    truth_th = 100

    net = UNet(len(im_tags), len(ma_tags))
    # net = UResNet(len(im_tags), len(ma_tags))
    # net = NestedUNet(len(im_tags),len(ma_tags))

    if args.load:
        net.load_state_dict(torch.load(args.load))
        print('Model loaded from {}'.format(args.load))

    if args.gpu:
        net.cuda()
        # cudnn.benchmark = True # faster convolutions, but more memory

    try:
        train_net(net=net,
                  im_tags=im_tags,
                  ma_tags=ma_tags,
                  truth_th=truth_th,
                  epochs=args.epochs,
                  samples=args.samples,
                  batch_size=args.batchsize,
                  lr=args.lr,
                  gpu=args.gpu,
                  img_scale=args.scale)
    except KeyboardInterrupt:
        torch.save(net.state_dict(), 'INTERRUPTED.pth')
        print('Saved interrupt')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
