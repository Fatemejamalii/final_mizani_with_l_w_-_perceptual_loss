import logging
import os
import numpy as np
import tensorflow as tf

from utils.general_utils import read_image , read_mask_image


class DataLoader(object):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.real_dataset = args.dataset_path.joinpath(f'real')
        self.wich_dataset = args.wich_dataset
        self.celeba_path =  args.celeba_path
        self.celeba_ws_path = args.celeba_ws_path
        trian_female = self.get_celeba_items(self.celeba_path + '/female')
        train_male = self.get_celeba_items(self.celeba_path + '/male')
        trian_mask = self.get_celeba_items(self.celeba_path + '/train_mask')
	
        ws_train_male = self.get_celeba_items(self.celeba_ws_path + '/ws_celeba_male')
        ws_train_female = self.get_celeba_items(self.celeba_ws_path + '/ws_celeba_female')
	
        ws_train_celeba = ws_train_female + ws_train_male
        train_celeba = trian_female + train_male
        self.celeba_list =  self.intersection(train_celeba, trian_mask)
        self.ws_list = self.intersection( ws_train_celeba, trian_mask)
        dataset = args.dataset_path.joinpath(f'dataset_{args.resolution}')
        
        if self.wich_dataset == 'dataset_256':
            self.ws_dataset = dataset.joinpath('ws')
            self.image_dataset = dataset.joinpath('images')
            self.mask_dataset = dataset.joinpath('image_masks')
            max_dir = max([x.name for x in self.image_dataset.iterdir()])
            self.max_ind = max([int(x.stem) for x in self.image_dataset.joinpath(max_dir).iterdir()])
            self.train_max_ind = args.train_data_size

            if self.train_max_ind >= self.max_ind:
                self.logger.warning('There is no validation data... using training data')
                self.min_val_ind = 0
                self.train_max_ind = self.max_ind
            else:
                self.min_val_ind = self.train_max_ind + 1
        else:
            self.ws_dataset = dataset.joinpath('ws')
            max_dir = len(self.celeba_list)
            self.max_ind = max_dir
            self.train_max_ind = max_dir
            self.min_val_ind = max_dir + 1
    
    def get_celeba_items(self,path):
        c_items = os.listdir(path)
        c_items.sort()
        items=[]
        for it in c_items:
            item = (os.path.join(path, it))
            items.append([it, item])
        return items

    def intersection(self,lst1, lst2):
      lst3 = []
      for i, j in lst1:
        for k, h in lst2:
          if i[:-4]==k[:-4]:
            lst3.append([j, h])  
      return lst3
        
    def get_image(self, is_train, black_list=None, is_real=False):
        # Default should be non-mutable
        if black_list is None:
            black_list = []

        max_fails = 10
        curr_fail = 0
        if is_train:
            min_ind, max_ind = 0, self.train_max_ind
        else:
            min_ind, max_ind = self.min_val_ind, self.max_ind

        while True:
            ind = np.random.randint(min_ind, max_ind)

            if ind in black_list:
                continue
            if self.wich_dataset == 'dataset_256':
                img_name = f'{ind:05d}.png'
                dir_name = f'{int(ind - ind % 1e3):05d}'
                if is_real:
                    img_path = self.real_dataset.joinpath(dir_name, img_name)
                else:
                    img_path = self.image_dataset.joinpath(dir_name, img_name)
                    mask_path = self.mask_dataset.joinpath(dir_name, img_name)
            else:
                img_path = self.celeba_list[ind][0]
                mask_path = self.celeba_list[ind][1]
                
            try:
                img_name = f'{ind:05d}.png'
                dir_name = f'{int(ind - ind % 1e3):05d}'
                img = read_image(img_path, self.args.resolution) 				
                masked_img, land_img = read_mask_image(img_path, mask_path, self.args.resolution)
				
				
                break
            except Exception as e:
                self.logger.warning(f'Failed reading image at {ind}. Error: {e}')

                # Try again with a different image...
                curr_fail += 1
                if curr_fail > max_fails:
                    raise IOError('Failed reading multiples images')
                continue

        return ind, img, masked_img , land_img

    def get_w_by_ind(self, ind):
        
        if self.wich_dataset == 'dataset_256':
	          dir_name = f'{int(ind - ind % 1e3):05d}'
	          img_name = f'{ind:05d}.npy'
	          w_path = self.ws_dataset.joinpath(dir_name, img_name)
        else:
            w_path = self.ws_list[ind][0]
            
        w = np.load(w_path)
	
        # Take one row while keeping dimension
        w = w[np.newaxis, 0]

        return w

    def get_real_w(self, is_train, black_list=None, is_real=False):
        ind = np.random.randint(0, self.max_ind)
        w = self.get_w_by_ind(ind)

        return ind, w, w, w

    def batch_samples(self, get_sample_func, is_train, black_list=None, is_real=False):
        batch = []
        masked_img_batch=[]
        land_img_batch=[]
        indices = []

        if not black_list:
            black_list = []
        for i in range(self.args.batch_size):
            ind, sample,sample_masked_img, sample_land_img  = get_sample_func(is_train, black_list, is_real)

            batch.append(sample)
            masked_img_batch.append(sample_masked_img)
            land_img_batch.append(sample_land_img)
            indices.append(ind)

        batch = tf.concat(batch, 0)
        masked_img_batch = tf.concat(masked_img_batch, 0)
        land_img_batch = tf.concat(land_img_batch, 0)
        return indices, batch, masked_img_batch, land_img_batch 

    def get_batch(self, is_train=True, is_cross=False, ws=True):
        black_list = []
        id_imgs_indices, id_img, id_mask, id_land = self.batch_samples(self.get_image, is_train)
        matching_ws = None

        self.logger.debug(f'ID images read: {id_imgs_indices}')
        black_list.extend(id_imgs_indices)

        if is_cross: 
            # Use real attr when args say so or when testing
            is_real_attr = (is_train and self.args.train_real_attr) or (not is_train and self.args.test_real_attr)
            black_list = [] if is_real_attr else black_list

            attr_imgs_indices, attr_img = self.batch_samples(self.get_image,
                                                             is_train,
                                                             black_list=black_list,
                                                             is_real=is_real_attr)

            self.logger.debug(f'Attr images read: {attr_imgs_indices}')

        else:
            if is_train:
                attr_img = id_land
                matching_ws = [self.get_w_by_ind(ind) for ind in id_imgs_indices]
                matching_ws = tf.concat(matching_ws, 0)
            else:
                attr_img = id_land

        if not is_train:
            return id_land, id_img, id_mask

        # Only for training
        real_img = None
        real_ws = None

        if self.args.train and self.args.reals:
            real_imgs_indices, real_img, real_img_mask, real_img_land = self.batch_samples(self.get_image, is_train, black_list=[], is_real=True)
            self.logger.debug(f'Real images read: {real_imgs_indices}')

        if ws:
            _, real_ws,_,_ = self.batch_samples(self.get_real_w, is_train)

        return attr_img, id_img, id_mask, real_ws, real_img, matching_ws

