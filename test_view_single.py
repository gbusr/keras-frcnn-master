from __future__ import division
import os
import cv2
import numpy as np
import sys
import pickle,cPickle
from optparse import OptionParser
import time
from keras_frcnn import config
import keras_frcnn.resnet_FC as nn
from keras import backend as K
from keras.layers import Input
from keras.models import Model
from keras_frcnn import roi_helpers
from PIL import Image
import pylab
import imageio
import matplotlib.pyplot as plt
# import bottleneck as bn

g_matlab_executable_path = '/usr/local/MATLAB/R2016b/bin/glnxa64/MATLAB'

sys.setrecursionlimit(40000)

old_cls = ['aeroplane','bicycle','boat','bottle','bus','car','chair','diningtable','motorbike','sofa','train', 'tvmonitor']
parser = OptionParser()

# parser.add_option("-p", "--path", dest="test_path", help="Path to test data.",default ='/home/gilad/ssd/keras-frcnn-master/test_data')
parser.add_option("-p", "--path", dest="test_path", help="Path to test data.",default ='/home/gilad/bar')

parser.add_option("-n", "--num_rois", dest="num_rois",
				help="Number of ROIs per iteration. Higher means more memory use.", default=32)
parser.add_option("--config_filename", dest="config_filename", help=
				"Location to read the metadata related to the training (generated when training).",
				default="config.pickle")
parser.add_option("--im_path", dest="im_path", help="Path to test data txt file.",default ='/home/gilad/Dropbox/Project/CNN/viewNet/data_txt/bus_wGT_original.txt')
parser.add_option("--test_path", dest="test_path", help="Path to test data txt file.",default ='./test_data')

(options, args) = parser.parse_args()

if not options.test_path:   # if filename is not given
	parser.error('Error: path to test data must be specified. Pass --path to command line')

config_output_filename = options.config_filename

with open(config_output_filename, 'rb') as f_in:
	C = pickle.load(f_in)

def softmax(x):
	"""Compute softmax values for each sets of scores in x."""
	x = x- np.min(x)
	e_x = np.exp(x - np.max(x))
	return e_x / e_x.sum(axis=0)


# filename ='/home/gilad/bar/real7.p'
# video_filename = "/home/gilad/ssd/keras-frcnn-master/a.mp4"
# save_flag = False
# visualise = True
# f = file(filename, 'r')
# tmp = cPickle.load(f)
# frames = []
# for i in range(len(tmp)):# for idx, img_name in enumerate(sorted(os.listdir(img_path))):
# 	if not img_name.lower().endswith(('.bmp', '.jpeg', '.jpg', '.png', '.tif', '.tiff')):
# 		continue
# 	print(img_name)
# 	filepath = os.path.join(img_path,img_name)
# 	img = cv2.imread(filepath)
#     frames.append(tmp[i][1])
# f.close()

# class_mapping= {'sheep': 19, 'horse': 18, 'bg': 20, 'bicycle': 10, 'motorbike': 6, 'cow': 16, 'bus': 3, 'aeroplane': 7, 'dog': 15, 'cat': 17, 'person': 12, 'train': 2, 'diningtable': 5, 'bottle': 9, 'sofa': 8, 'pottedplant': 13, 'tvmonitor': 0, 'chair': 4, 'bird': 14, 'boat': 1, 'car': 11}

class_mapping = {'sheep': 5, 'bottle': 8, 'horse': 15, 'bg': 20, 'bicycle': 17, 'motorbike': 16, 'cow': 12, 'sofa': 14, 'dog': 0, 'bus': 11, 'cat': 10, 'person': 6, 'train': 4, 'diningtable': 13, 'aeroplane': 19, 'car': 1, 'pottedplant': 2, 'tvmonitor': 7, 'chair': 9, 'bird': 3, 'boat': 18}
C.class_mapping = class_mapping


base_path = os.getcwd()
weight_path = os.path.join(base_path,'models/model_FC_weight_best.hdf5')
# weight_path = os.path.join(base_path,'models/model_frcnn_new.hdf5')
# C.anchor_box_scales = [128,256,512]
# turn off any data augmentation at test time
C.use_horizontal_flips = False
C.use_vertical_flips = False
C.rot_90 = False
count = 0
good_img = 0
not_good = 0
img_path = options.test_path

def format_img_size(img, C):
	""" formats the image size based on config """
	img_min_side = float(C.im_size)
	(height,width,_) = img.shape
		
	if width <= height:
		ratio = img_min_side/width
		new_height = int(ratio * height)
		new_width = int(img_min_side)
	else:
		ratio = img_min_side/height
		new_width = int(ratio * width)
		new_height = int(img_min_side)
	img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
	return img, ratio	

def format_img_channels(img, C,rgb = False):
	""" formats the image channels based on config """
	if not(rgb):
		img = img[:, :, (2, 1, 0)]
	img = img.astype(np.float32)
	img[:, :, 0] -= C.img_channel_mean[0]
	img[:, :, 1] -= C.img_channel_mean[1]
	img[:, :, 2] -= C.img_channel_mean[2]
	img /= C.img_scaling_factor
	img = np.transpose(img, (2, 0, 1))
	img = np.expand_dims(img, axis=0)
	return img

def format_img(img, C ,rgb = False):
	""" formats an image for model prediction based on config """
	img, ratio = format_img_size(img, C)
	img = format_img_channels(img, C,rgb)
	return img, ratio

# Method to transform the coordinates of the bounding box to its original size
def get_real_coordinates(ratio, x1, y1, x2, y2):

	real_x1 = int(round(x1 // ratio))
	real_y1 = int(round(y1 // ratio))
	real_x2 = int(round(x2 // ratio))
	real_y2 = int(round(y2 // ratio))

	return (real_x1, real_y1, real_x2 ,real_y2)


vnum_test = 24
azimuth_vec = np.concatenate(
    ([0], np.linspace((360. / (vnum_test * 2)), 360. - (360. / (vnum_test * 2)), vnum_test)),
    axis=0)

def find_interval(azimuth, azimuth_vec):
    for i in range(len(azimuth_vec)):
        if azimuth < azimuth_vec[i]:
            break
    ind = i
    if azimuth > azimuth_vec[-1]:
        ind = 1
    return ind

class_mapping = C.class_mapping

if 'bg' not in class_mapping:
	class_mapping['bg'] = len(class_mapping)

class_mapping = {v: k for k, v in class_mapping.items()}
print(class_mapping)
class_to_color = {class_mapping[v]: np.random.randint(0, 255, 3) for v in class_mapping}
C.num_rois = int(options.num_rois)

if K.image_dim_ordering() == 'th':
	input_shape_img = (3, None, None)
	input_shape_features = (1024, None, None)
else:
	input_shape_img = (None, None, 3)
	input_shape_features = (None, None, 1024)


img_input = Input(shape=input_shape_img)
roi_input = Input(shape=(C.num_rois, 4))
feature_map_input = Input(shape=input_shape_features)

# define the base network (resnet here, can be VGG, Inception, etc)
shared_layers = nn.nn_base(img_input, trainable=True)

# define the RPN, built on the base layers
num_anchors = len(C.anchor_box_scales) * len(C.anchor_box_ratios)
rpn_layers = nn.rpn(shared_layers, num_anchors)

classifier,_= nn.classifier(feature_map_input, roi_input, C.num_rois, nb_classes=len(class_mapping))

model_rpn = Model(img_input, rpn_layers)
model_classifier_only = Model([feature_map_input, roi_input], classifier)

model_classifier = Model([feature_map_input, roi_input], classifier)

model_rpn.load_weights(weight_path, by_name=True)
model_classifier.load_weights(weight_path, by_name=True)

model_rpn.compile(optimizer='sgd', loss='mse')
model_classifier.compile(optimizer='sgd', loss='mse')

all_imgs = []

classes = {}

def pred2bins(az_pred):
    '''
    find the bin for every quntization by sum
    '''
    sum_az = np.cumsum(az_pred)
    pyr_bins = np.zeros([1,4])
    vnum = [4, 8, 16, 24]
    for ii in range(len(vnum)):
        tmp_azimuth = np.concatenate(([0], np.linspace((360. / (vnum[ii] * 2)), 360. - (360. / (vnum[ii] * 2)), vnum[ii])),
                                 axis=0)
        sum_vec = np.diff([sum_az[i] for i in tmp_azimuth.astype(int)])
        sum_vec[0] += sum_az[359] - sum_vec[-1]
        pyr_bins[0,ii] = np.argmax(sum_vec) + 1 #becuse the bins starts at 1
    return pyr_bins

bbox_threshold = 0.7
rgb = False
#### open images from folder
def top_n_indexes(arr, n):
	id = np.argsort(arr)[-n:]
	val = arr[id]
	return id,val

visualize = True
save_flag = False
for idx, img_name in enumerate(sorted(os.listdir(img_path))):
	if not img_name.lower().endswith(('.bmp', '.jpeg', '.jpg', '.png', '.tif', '.tiff')):
		continue
	print(img_name)
	filepath = os.path.join(img_path,img_name)
	img = cv2.imread(filepath)

#### open images from file

# with open(options.im_path,'r') as f:
# 	data = f.readlines()
# for line in data:
# 	words = line.split()
# 	filepath = words[0]
# 	cls_gt = words[1]
# 	az_gt = int(words[2])
# 	el_gt = words[3]
# 	t_gt = words[4]
# 	# try to read to original image and not the image after BBox that is in the txt file
# 	# string = os.path.split(filepath)
# 	# tmp_str = string[0][:string[0].find('JPEG')]
# 	# filepath = os.path.join(tmp_str, 'JPEGImages', string[1])
# 	img = cv2.imread(filepath)



### open images from video
# visualize = False
# save_flag = True
# obj_name = 'bicycle'
# file_name = '{}1_200'.format(obj_name)
# video_filename = 'video/{}.mp4'.format(file_name)
# result_folder = 'results_imgs/{}'.format(file_name)
# if not(os.path.exists(result_folder)):
# 	os.mkdir(result_folder)
# vid = imageio.get_reader(video_filename, 'ffmpeg')
# rgb = True
# start_frame = 150
# end_frame = vid._meta['nframes'] - 30
# for num in range(start_frame ,end_frame,10):
# 	# num =
# 	img = vid.get_data(num)
# 	# img = cv2.flip(vid.get_data(num),1)
# #

	if img is None:
		not_good += 1
		continue
	else:
		good_img += 1
	# if good_img%50 == 0:
		# print ('created {}/{} images'.format(good_img,end_frame-start_frame))
	X, ratio = format_img(img, C,rgb=rgb)

	if K.image_dim_ordering() == 'tf':
		X = np.transpose(X, (0, 2, 3, 1))

	# get the feature maps and output from the RPN
	[Y1, Y2, F] = model_rpn.predict(X)

	R = roi_helpers.rpn_to_roi(Y1, Y2, C, K.image_dim_ordering(), overlap_thresh=0.7)

	# convert from (x1,y1,x2,y2) to (x,y,w,h)
	R[:, 2] -= R[:, 0]
	R[:, 3] -= R[:, 1]

	# apply the spatial pyramid pooling to the proposed regions
	bboxes = {}
	probs = {}
	azimuths ={}
	prob = {}
	az_total = {}
	for jk in range(R.shape[0]//C.num_rois + 1):
		ROIs = np.expand_dims(R[C.num_rois*jk:C.num_rois*(jk+1), :], axis=0)
		if ROIs.shape[1] == 0:
			break

		if jk == R.shape[0]//C.num_rois:
			#pad R
			curr_shape = ROIs.shape
			target_shape = (curr_shape[0],C.num_rois,curr_shape[2])
			ROIs_padded = np.zeros(target_shape).astype(ROIs.dtype)
			ROIs_padded[:, :curr_shape[1], :] = ROIs
			ROIs_padded[0, curr_shape[1]:, :] = ROIs[0, 0, :]
			ROIs = ROIs_padded

		[P_cls, P_regr,P_view] = model_classifier_only.predict([F, ROIs])

		for ii in range(P_cls.shape[1]):

			if np.max(P_cls[0, ii, :]) < bbox_threshold or np.argmax(P_cls[0, ii, :]) == (P_cls.shape[2] - 1):
				continue
			cls_num = np.argmax(P_cls[0, ii, :])
			cls_name = class_mapping[cls_num]
			cls_view = softmax(P_view[0, ii, 360*cls_num:360*(cls_num+1)])
			# cls_name_gt = old_cls[int(cls_gt)]
			# if cls_name == cls_name_gt:
			# 	print(np.argmax(cls_view,axis=0))
			if cls_name not in bboxes:
				bboxes[cls_name] = []
				probs[cls_name] = []
				azimuths[cls_name] = []
				prob[cls_name] = []
				az_total[cls_name] = np.zeros(360)

			(x, y, w, h) = ROIs[0, ii, :]

			try:
				(tx, ty, tw, th) = P_regr[0, ii, 4*cls_num:4*(cls_num+1)]
				tx /= C.classifier_regr_std[0]
				ty /= C.classifier_regr_std[1]
				tw /= C.classifier_regr_std[2]
				th /= C.classifier_regr_std[3]
				x, y, w, h = roi_helpers.apply_regr(x, y, w, h, tx, ty, tw, th)
			except:
				pass
			bboxes[cls_name].append([C.rpn_stride*x, C.rpn_stride*y, C.rpn_stride*(x+w), C.rpn_stride*(y+h)])
			probs[cls_name].append(np.max(P_cls[0, ii, :]))
			azimuths[cls_name].append(np.argmax(cls_view,axis=0))
			prob[cls_name].append(cls_view)
			ids,vals = top_n_indexes(cls_view,10)
			for ind,val in zip(ids,vals):
				az_total[cls_name][ind]+= val * np.max(P_cls[0, ii, :])

	all_dets = []

	for key in bboxes:
		# if not(key == obj_name):
		# 	continue
		bbox = np.array(bboxes[key])
		prob_array = np.array(probs[key])
		azimuth = np.array(azimuths[key])
		az_calc = np.argmax(np.array(az_total[key]))
		new_boxes, new_probs,new_az = roi_helpers.non_max_suppression_fast(bbox,prob_array,azimuth,overlap_thresh=0.5,use_az=True)
		for jk in range(new_boxes.shape[0]):
			(x1, y1, x2, y2) = new_boxes[jk,:]

			(real_x1, real_y1, real_x2, real_y2) = get_real_coordinates(ratio, x1, y1, x2, y2)

			cv2.rectangle(img,(real_x1, real_y1), (real_x2, real_y2), (int(class_to_color[key][0]), int(class_to_color[key][1]), int(class_to_color[key][2])),2)

			# textLabel = '{}: {},azimuth : {}'.format(key,int(100*new_probs[jk]),new_az[jk])
			textLabel = 'az {}'.format(new_az[jk])

			all_dets.append((key,100*new_probs[jk]))

			(retval,baseLine) = cv2.getTextSize(textLabel,cv2.FONT_HERSHEY_COMPLEX,1,1)
			textOrg = (real_x1, real_y1+15)

			cv2.rectangle(img, (textOrg[0] - 1, textOrg[1]+baseLine - 1), (textOrg[0]+retval[0] + 1, textOrg[1]-retval[1] - 1), (0, 0, 0), 2)
			cv2.rectangle(img, (textOrg[0] - 1,textOrg[1]+baseLine - 1), (textOrg[0]+retval[0] + 1, textOrg[1]-retval[1] - 1), (255, 255, 255), -1)
			cv2.putText(img, textLabel, textOrg, cv2.FONT_HERSHEY_DUPLEX, 1, (0, 0, 0), 1)

	## azimuth calculations

	# true_bin = find_interval(az_gt,azimuth_vec)
	# true_flag = False
	# try:
	# 	test_az = np.array(azimuths[cls_name_gt])
	# 	# test_az = np.array(new_az)
	# 	for jj in range(len(test_az)):
	# 		tmp_bin = find_interval(test_az[jj],azimuth_vec)
	# 		if tmp_bin == true_bin:
	# 			true_flag = True
	# 	count += true_flag
	# except:
	# 	not_good+=1


	## display

	# print('Elapsed time = {}'.format(time.time() - st))
	# print('real az is {}'.format(az_gt))
	# print('pred az is {}'.format(new_az[:]))
	# print(all_dets)

	if visualize:
		img = img[:,:,(2,1,0)]
		# img1=img
		obj_name = 'aeroplane'
		prob1 = prob[obj_name][-2]
		tmp_img = np.expand_dims(prob1, axis=2)
		tmp_img = tmp_img - min(tmp_img)
		tmp_img = 255 - tmp_img / max(tmp_img) * 255
		tmp_img = np.tile(tmp_img, [30, 1, 3])
		tmp_img[:, new_az[0], :] = [0, 255, 0]

		imgs = [Image.fromarray(img.astype('uint8')), Image.fromarray(tmp_img.astype('uint8'))]
		# imgs    = [ im, a]
		# pick the image which is the smallest, and resize the others to match it (can be arbitrary image shape here)
		min_shape = sorted([i.size for i in imgs])[1][0]
		imgs_comb = []
		for ii in range(len(imgs)):
		   imgs_comb.append(imgs[ii].resize([min_shape, imgs[ii].size[1]]))
		imgs_comb = np.vstack((imgs_comb[0], imgs_comb[1]))
		im  = Image.fromarray(imgs_comb.astype('uint8'),'RGB')
		# im  = Image.fromarray(img.astype('uint8'),'RGB')
		im.show()
		# prob1 = prob[obj_name][-2]
		# id,val =  top_n_indexes(prob1,5)
		# az_real = 0
		# fig = plt.figure()
		# plt.subplot(211)
		# plt.title('image {}'.format(num))
		# im = Image.fromarray(img.astype('uint8'), 'RGB')
		# # im.show()
		# plt.imshow(im)
		# # plt.interactive(True)False
		# plt.subplot(212)
		# true180 = (az_real + 180) % 360
		# plt.plot(az_real * np.ones([10, ]), np.linspace(0, prob1[az_real], 10), '-b', label='true azimuth')
		# plt.plot(true180 * np.ones([10, ]), np.linspace(0, prob1[true180], 10), '*b', label='180 from true azimuth')
		# plt.plot(new_az * np.ones([10, ]), np.linspace(0, prob1[new_az], 10), '-r', label='predict azimuth')
		# plt.plot(np.asarray(prob1), '-g')
		# # plt.legend()
		# plt.title('az_calc {} az pred {}'.format(az_calc,new_az))
		# # plt.title(
		# # 	'true %s,pred %s ,pred_lr %s error is %s and its %s' % (
		# # 	az_real, az_prob_orig, az_prob_lr, ang_err[0], status_name))
		# plt.show()


	# cv2.imshow('img', img)
	# cv2.waitKey(0)
# 	if save_flag:
# 	   # cv2.imwrite('./results_imgs/{}'.format(img_name),img)
# 	   img = img[:, :, (2, 1, 0)]
# 	   prob1 = prob[obj_name][-2]
# 	   tmp_img = np.expand_dims(prob1, axis=2)
# 	   tmp_img = tmp_img - min(tmp_img)
# 	   tmp_img = 255 - tmp_img / max(tmp_img) * 255
# 	   tmp_img = np.tile(tmp_img, [30, 1, 3])
# 	   tmp_img[:, new_az[0], :] = [0, 255, 0]
#
# 	   imgs = [Image.fromarray(img.astype('uint8')), Image.fromarray(tmp_img.astype('uint8'))]
# 	   # imgs    = [ im, a]
# 	   # pick the image which is the smallest, and resize the others to match it (can be arbitrary image shape here)
# 	   min_shape = sorted([i.size for i in imgs])[1][0]
# 	   imgs_comb = []
# 	   for ii in range(len(imgs)):
# 		   imgs_comb.append(imgs[ii].resize([min_shape, imgs[ii].size[1]]))
# 	   imgs_comb = np.vstack((imgs_comb[0], imgs_comb[1]))
# 	   # img = Image.fromarray(imgs_comb)
# 	   cv2.imwrite(result_folder+'/{0:04}.png'.format(num),imgs_comb)
# 		# print('save')
# if save_flag:
# 	curr_dir = os.getcwd()
# 	print('true count is {} out of {} and {} of them are not good'.format(count,good_img,not_good))
# 	matlab_cmd = "addpath('%s'); img2vid('%s','%s',%s);" % (curr_dir,os.path.join(curr_dir,result_folder),os.path.join(curr_dir,'results_imgs/{}'.format(file_name)),15)
# 	print matlab_cmd
# 	os.system('%s -nodisplay -r "try %s ; catch; end; quit;"' % (g_matlab_executable_path, matlab_cmd))