#
# load.py : utils on generators / lists of ids to transform from strings to
#           cropped images and masks

import os
import h5py
import numpy as np
import matplotlib.pyplot as plt


def load(file, event, tags):
  data = h5py.File(file, 'r')
  frames = []
  for tag in tags:
    f = data.get('/%d/%s'%(event, tag))
    if f is None:
      return None
    frames.append(np.array(f))
  img = np.stack(frames, axis = 2)
  img = np.transpose(img, axes=[1, 0, 2])
  return img

def rebin(a, shape):
  sh = shape[0],a.shape[0]//shape[0],shape[1],a.shape[1]//shape[1]
  if len(a.shape) == 3:
    sh = shape[0],a.shape[0]//shape[0],shape[1],a.shape[1]//shape[1],a.shape[2]
  return a.reshape(sh).mean(3).mean(1)

def plot_img(img):
  for ich in range(img.shape[2]) :
    fig = plt.figure()
    a = fig.add_subplot(1, 1, 1)
    a.set_title('CH{}'.format(ich))
    frame_ma = np.ma.array(np.transpose(img[:,:,ich], axes=[1, 0]))
    # plt.imshow(np.ma.masked_where(frame_ma<=0,frame_ma), cmap="bwr_r", origin='lower')
    plt.imshow(frame_ma, cmap="bwr", origin='lower')
    plt.clim(-1,1)
    # plt.colorbar()
    plt.grid()
  plt.show()

def plot_mask(mask):
  plt.figure()
  # plt.gca().set_title('Mask')
  plt.imshow(np.transpose(mask, axes=[1, 0])
  , cmap="bwr"
  , origin='lower'
  # , aspect='auto'
  )
  # print("Mask non-zero",np.count_nonzero(mask))
  # plt.colorbar()
  plt.clim(-1,1)
  plt.grid()
  plt.show()

def get_hwc_img(file, event, tags, scale, crop0, crop1, norm):
  """From a list of tuples, returns the correct cropped img"""
  im = load(file, event, tags)
  if im is None:
    return None
  im = rebin(im, [im.shape[0]//scale[0],im.shape[1]//scale[1]])/norm
  im = im[crop0[0]:crop0[1], crop1[0]:crop1[1], :]
  return im

def get_hwc_imgs(file, ids, tags, scale, crop0, crop1, norm):
  """From a list of tuples, returns the correct cropped img"""
  for id in ids:
    im = get_hwc_img(file[id[0]], id[1], tags, scale, crop0, crop1, norm)
    if im is None:
      print(f'warn: {file[id[0]]} {id[1]} {tags} is None!')
      continue
    yield im

def get_chw_imgs(file, ids, tags, scale, crop0, crop1, norm):
  """From a list of tuples, returns the correct cropped img"""
  for id in ids:
    im = get_hwc_img(file[id[0]], id[1], tags, scale, crop0, crop1, norm)
    if im is None:
      print(f'warn: {file[id[0]]} {id[1]} {tags} is None!')
      continue
    im = np.transpose(im, axes=[2, 0, 1])
    yield im

def get_masks(file, ids, tags, scale, crop0, crop1, threshold):
  """From a list of tuples, returns the correct cropped img"""
  for id in ids:
    im = load(file[id[0]], id[1], tags)
    if im is None:
      print(f'warn: {file[id[0]]} {id[1]} {tags} is None!')
      continue
    im = im.reshape(im.shape[0],im.shape[1])
    im = rebin(im, [im.shape[0]//scale[0],im.shape[1]//scale[1]])
    im = im[crop0[0]:crop0[1], crop1[0]:crop1[1]]
    im[im<=threshold] = 0
    im[im>threshold] = 1
    yield im