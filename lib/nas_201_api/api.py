##################################################
# Copyright (c) Xuanyi Dong [GitHub D-X-Y], 2019 #
############################################################################################
# NAS-Bench-201: Extending the Scope of Reproducible Neural Architecture Search, ICLR 2020 #
############################################################################################
# NAS-Bench-201-v1_0-e61699.pth : 6219 architectures are trained once, 1621 architectures are trained twice, 7785 architectures are trained three times. `LESS` only supports CIFAR10-VALID.
#
#
#
import os, sys, copy, random, torch, numpy as np
from collections import OrderedDict, defaultdict


def print_information(information, extra_info=None, show=False):
  dataset_names = information.get_dataset_names()
  strings = [information.arch_str, 'datasets : {:}, extra-info : {:}'.format(dataset_names, extra_info)]
  def metric2str(loss, acc):
    return 'loss = {:.3f}, top1 = {:.2f}%'.format(loss, acc)

  for ida, dataset in enumerate(dataset_names):
    #flop, param, latency = information.get_comput_costs(dataset)
    metric = information.get_comput_costs(dataset)
    flop, param, latency = metric['flops'], metric['params'], metric['latency']
    str1 = '{:14s} FLOP={:6.2f} M, Params={:.3f} MB, latency={:} ms.'.format(dataset, flop, param, '{:.2f}'.format(latency*1000) if latency is not None and latency > 0 else None)
    train_info = information.get_metrics(dataset, 'train')
    if dataset == 'cifar10-valid':
      valid_info = information.get_metrics(dataset, 'x-valid')
      str2 = '{:14s} train : [{:}], valid : [{:}]'.format(dataset, metric2str(train_info['loss'], train_info['accuracy']), metric2str(valid_info['loss'], valid_info['accuracy']))
    elif dataset == 'cifar10':
      test__info = information.get_metrics(dataset, 'ori-test')
      str2 = '{:14s} train : [{:}], test  : [{:}]'.format(dataset, metric2str(train_info['loss'], train_info['accuracy']), metric2str(test__info['loss'], test__info['accuracy']))
    else:
      valid_info = information.get_metrics(dataset, 'x-valid')
      test__info = information.get_metrics(dataset, 'x-test')
      str2 = '{:14s} train : [{:}], valid : [{:}], test : [{:}]'.format(dataset, metric2str(train_info['loss'], train_info['accuracy']), metric2str(valid_info['loss'], valid_info['accuracy']), metric2str(test__info['loss'], test__info['accuracy']))
    strings += [str1, str2]
  if show: print('\n'.join(strings))
  return strings

"""
This is the class for API of NAS-Bench-201.
"""
class NASBench201API(object):

  """ The initialization function that takes the dataset file path (or a dict loaded from that path) as input. """
  def __init__(self, file_path_or_dict, verbose=True):
    if isinstance(file_path_or_dict, str):
      if verbose: print('try to create the NAS-Bench-201 api from {:}'.format(file_path_or_dict))
      assert os.path.isfile(file_path_or_dict), 'invalid path : {:}'.format(file_path_or_dict)
      file_path_or_dict = torch.load(file_path_or_dict)
    elif isinstance(file_path_or_dict, dict):
      file_path_or_dict = copy.deepcopy( file_path_or_dict )
    else: raise ValueError('invalid type : {:} not in [str, dict]'.format(type(file_path_or_dict)))
    assert isinstance(file_path_or_dict, dict), 'It should be a dict instead of {:}'.format(type(file_path_or_dict))
    self.verbose = verbose # [TODO] a flag indicating whether to print more logs
    keys = ('meta_archs', 'arch2infos', 'evaluated_indexes')
    for key in keys: assert key in file_path_or_dict, 'Can not find key[{:}] in the dict'.format(key)
    self.meta_archs = copy.deepcopy( file_path_or_dict['meta_archs'] )
    self.arch2infos_less = OrderedDict()
    self.arch2infos_full = OrderedDict()
    for xkey in sorted(list(file_path_or_dict['arch2infos'].keys())):
      all_info = file_path_or_dict['arch2infos'][xkey]
      self.arch2infos_less[xkey] = ArchResults.create_from_state_dict( all_info['less'] )
      self.arch2infos_full[xkey] = ArchResults.create_from_state_dict( all_info['full'] )
    self.evaluated_indexes = sorted(list(file_path_or_dict['evaluated_indexes']))
    self.archstr2index = {}
    for idx, arch in enumerate(self.meta_archs):
      #assert arch.tostr() not in self.archstr2index, 'This [{:}]-th arch {:} already in the dict ({:}).'.format(idx, arch, self.archstr2index[arch.tostr()])
      assert arch not in self.archstr2index, 'This [{:}]-th arch {:} already in the dict ({:}).'.format(idx, arch, self.archstr2index[arch])
      self.archstr2index[ arch ] = idx

  def __getitem__(self, index):
    return copy.deepcopy( self.meta_archs[index] )

  def __len__(self):
    return len(self.meta_archs)

  def __repr__(self):
    return ('{name}({num}/{total} architectures)'.format(name=self.__class__.__name__, num=len(self.evaluated_indexes), total=len(self.meta_archs)))

  def random(self):
    return random.randint(0, len(self.meta_archs)-1)

  # This function is used to query the index of an architecture in the search space.
  # The input arch can be an architecture string such as '|nor_conv_3x3~0|+|nor_conv_3x3~0|avg_pool_3x3~1|+|skip_connect~0|nor_conv_3x3~1|skip_connect~2|'
  # or an instance that has the 'tostr' function that can generate the architecture string.
  # This function will return the index.
  #   If return -1, it means this architecture is not in the search space.
  #   Otherwise, it will return an int in [0, the-number-of-candidates-in-the-search-space).
  def query_index_by_arch(self, arch):
    if isinstance(arch, str):
      if arch in self.archstr2index: arch_index = self.archstr2index[ arch ]
      else                         : arch_index = -1
    elif hasattr(arch, 'tostr'):
      if arch.tostr() in self.archstr2index: arch_index = self.archstr2index[ arch.tostr() ]
      else                                 : arch_index = -1
    else: arch_index = -1
    return arch_index

  # Overwrite all information of the 'index'-th architecture in the search space.
  # It will load its data from 'archive_root'.
  def reload(self, archive_root, index):
    assert os.path.isdir(archive_root), 'invalid directory : {:}'.format(archive_root)
    xfile_path = os.path.join(archive_root, '{:06d}-FULL.pth'.format(index))
    assert 0 <= index < len(self.meta_archs), 'invalid index of {:}'.format(index)
    assert os.path.isfile(xfile_path), 'invalid data path : {:}'.format(xfile_path)
    xdata = torch.load(xfile_path)
    assert isinstance(xdata, dict) and 'full' in xdata and 'less' in xdata, 'invalid format of data in {:}'.format(xfile_path)
    self.arch2infos_less[index] = ArchResults.create_from_state_dict( xdata['less'] )
    self.arch2infos_full[index] = ArchResults.create_from_state_dict( xdata['full'] )
  
  # This function is used to query the information of a specific archiitecture
  # 'arch' can be an architecture index or an architecture string
  # When use_12epochs_result=True, the hyper-parameters used to train a model are in 'configs/nas-benchmark/CIFAR.config'
  # When use_12epochs_result=False, the hyper-parameters used to train a model are in 'configs/nas-benchmark/LESS.config'
  # The difference between these two configurations are the number of training epochs, which is 200 in CIFAR.config and 12 in LESS.config.
  def query_by_arch(self, arch, use_12epochs_result=False):
    if isinstance(arch, int):
      arch_index = arch
    else:
      arch_index = self.query_index_by_arch(arch)
    if arch_index == -1: return None # the following two lines are used to support few training epochs
    if use_12epochs_result: arch2infos = self.arch2infos_less
    else                  : arch2infos = self.arch2infos_full
    if arch_index in arch2infos:
      strings = print_information(arch2infos[ arch_index ], 'arch-index={:}'.format(arch_index))
      return '\n'.join(strings)
    else:
      print ('Find this arch-index : {:}, but this arch is not evaluated.'.format(arch_index))
      return None

  # This 'query_by_index' function is used to query information with the training of 12 epochs or 200 epochs.
  # ------
  # If use_12epochs_result=True, we train the model by 12 epochs (see config in configs/nas-benchmark/LESS.config)
  # If use_12epochs_result=False, we train the model by 200 epochs (see config in configs/nas-benchmark/CIFAR.config)
  # ------
  # If dataname is None, return the ArchResults
  # else, return a dict with all trials on that dataset (the key is the seed)
  # Options are 'cifar10-valid', 'cifar10', 'cifar100', 'ImageNet16-120'.
  #  -- cifar10-valid : training the model on the CIFAR-10 training set.
  #  -- cifar10 : training the model on the CIFAR-10 training + validation set.
  #  -- cifar100 : training the model on the CIFAR-100 training set.
  #  -- ImageNet16-120 : training the model on the ImageNet16-120 training set.
  def query_by_index(self, arch_index, dataname=None, use_12epochs_result=False):
    if use_12epochs_result: basestr, arch2infos = '12epochs' , self.arch2infos_less
    else                  : basestr, arch2infos = '200epochs', self.arch2infos_full
    assert arch_index in arch2infos, 'arch_index [{:}] does not in arch2info with {:}'.format(arch_index, basestr)
    archInfo = copy.deepcopy( arch2infos[ arch_index ] )
    if dataname is None: return archInfo
    else:
      assert dataname in archInfo.get_dataset_names(), 'invalid dataset-name : {:}'.format(dataname)
      info = archInfo.query(dataname)
      return info

  def query_meta_info_by_index(self, arch_index, use_12epochs_result=False):
    if use_12epochs_result: basestr, arch2infos = '12epochs' , self.arch2infos_less
    else                  : basestr, arch2infos = '200epochs', self.arch2infos_full
    assert arch_index in arch2infos, 'arch_index [{:}] does not in arch2info with {:}'.format(arch_index, basestr)
    archInfo = copy.deepcopy( arch2infos[ arch_index ] )
    return archInfo

  def find_best(self, dataset, metric_on_set, FLOP_max=None, Param_max=None, use_12epochs_result=False):
    if use_12epochs_result: basestr, arch2infos = '12epochs' , self.arch2infos_less
    else                  : basestr, arch2infos = '200epochs', self.arch2infos_full
    best_index, highest_accuracy = -1, None
    for i, idx in enumerate(self.evaluated_indexes):
      info = arch2infos[idx].get_comput_costs(dataset)
      flop, param, latency = info['flops'], info['params'], info['latency']
      if FLOP_max  is not None and flop  > FLOP_max : continue
      if Param_max is not None and param > Param_max: continue
      xinfo = arch2infos[idx].get_metrics(dataset, metric_on_set)
      loss, accuracy = xinfo['loss'], xinfo['accuracy']
      if best_index == -1:
        best_index, highest_accuracy = idx, accuracy
      elif highest_accuracy < accuracy:
        best_index, highest_accuracy = idx, accuracy
    return best_index, highest_accuracy

  # return the topology structure of the `index`-th architecture
  def arch(self, index):
    assert 0 <= index < len(self.meta_archs), 'invalid index : {:} vs. {:}.'.format(index, len(self.meta_archs))
    return copy.deepcopy(self.meta_archs[index])

  """
  This function is used to obtain the trained weights of the `index`-th architecture on `dataset` with the seed of `seed`
  Args [seed]:
    -- None : return a dict containing the trained weights of all trials, where each key is a seed and its corresponding value is the weights.
    -- a interger : return the weights of a specific trial, whose seed is this interger.
  Args [use_12epochs_result]:
    -- True : train the model by 12 epochs
    -- False : train the model by 200 epochs
  """
  def get_net_param(self, index, dataset, seed, use_12epochs_result=False):
    if use_12epochs_result: basestr, arch2infos = '12epochs' , self.arch2infos_less
    else                  : basestr, arch2infos = '200epochs', self.arch2infos_full
    archresult = arch2infos[index]
    return archresult.get_net_param(dataset, seed)
  
  """
  This function is used to obtain the configuration for the `index`-th architecture on `dataset`.
  Args [dataset] (4 possible options):
    -- cifar10-valid : training the model on the CIFAR-10 training set.
    -- cifar10 : training the model on the CIFAR-10 training + validation set.
    -- cifar100 : training the model on the CIFAR-100 training set.
    -- ImageNet16-120 : training the model on the ImageNet16-120 training set.
  This function will return a dict.
  ========= Some examlpes for using this function:
  config = api.get_net_config(128, 'cifar10')
  """
  def get_net_config(self, index, dataset):
    archresult = self.arch2infos_full[index]
    all_results = archresult.query(dataset, None)
    if len(all_results) == 0: raise ValueError('can not find one valid trial for the {:}-th architecture on {:}'.format(index, dataset))
    for seed, result in all_results.items():
      return result.get_config(None)
      #print ('SEED [{:}] : {:}'.format(seed, result))
    raise ValueError('Impossible to reach here!')

  # obtain the cost metric for the `index`-th architecture on a dataset
  def get_cost_info(self, index, dataset, use_12epochs_result=False):
    if use_12epochs_result: basestr, arch2infos = '12epochs' , self.arch2infos_less
    else                  : basestr, arch2infos = '200epochs', self.arch2infos_full
    archresult = arch2infos[index]
    return archresult.get_comput_costs(dataset)

  # obtain the metric for the `index`-th architecture
  # `dataset` indicates the dataset:
  #   'cifar10-valid'  : using the proposed train set of CIFAR-10 as the training set
  #   'cifar10'        : using the proposed train+valid set of CIFAR-10 as the training set
  #   'cifar100'       : using the proposed train set of CIFAR-100 as the training set
  #   'ImageNet16-120' : using the proposed train set of ImageNet-16-120 as the training set
  # `iepoch` indicates the index of training epochs from 0 to 11/199.
  #   When iepoch=None, it will return the metric for the last training epoch
  #   When iepoch=11, it will return the metric for the 11-th training epoch (starting from 0)
  # `use_12epochs_result` indicates different hyper-parameters for training
  #   When use_12epochs_result=True, it trains the network with 12 epochs and the LR decayed from 0.1 to 0 within 12 epochs
  #   When use_12epochs_result=False, it trains the network with 200 epochs and the LR decayed from 0.1 to 0 within 200 epochs
  # `is_random`
  #   When is_random=True, the performance of a random architecture will be returned
  #   When is_random=False, the performanceo of all trials will be averaged.
  def get_more_info(self, index, dataset, iepoch=None, use_12epochs_result=False, is_random=True):
    if use_12epochs_result: basestr, arch2infos = '12epochs' , self.arch2infos_less
    else                  : basestr, arch2infos = '200epochs', self.arch2infos_full
    archresult = arch2infos[index]
    # if randomly select one trial, select the seed at first
    if isinstance(is_random, bool) and is_random:
      seeds = archresult.get_dataset_seeds(dataset)
      is_random = random.choice(seeds)
    if dataset == 'cifar10-valid':
      train_info = archresult.get_metrics(dataset, 'train'   , iepoch=iepoch, is_random=is_random)
      valid_info = archresult.get_metrics(dataset, 'x-valid' , iepoch=iepoch, is_random=is_random)
      try:
        test__info = archresult.get_metrics(dataset, 'ori-test', iepoch=iepoch, is_random=is_random)
      except:
        test__info = None
      total      = train_info['iepoch'] + 1
      xifo = {'train-loss'    : train_info['loss'],
              'train-accuracy': train_info['accuracy'],
              'train-per-time': None if train_info['all_time'] is None else train_info['all_time'] / total,
              'train-all-time': train_info['all_time'],
              'valid-loss'    : valid_info['loss'],
              'valid-accuracy': valid_info['accuracy'],
              'valid-all-time': valid_info['all_time'],
              'valid-per-time': None if valid_info['all_time'] is None else valid_info['all_time'] / total}
      if test__info is not None:
        xifo['test-loss']     = test__info['loss']
        xifo['test-accuracy'] = test__info['accuracy']
      return xifo
    else:
      train_info = archresult.get_metrics(dataset, 'train'   , iepoch=iepoch, is_random=is_random)
      try:
        if dataset == 'cifar10':
          test__info = archresult.get_metrics(dataset, 'ori-test', iepoch=iepoch, is_random=is_random)
        else:
          test__info = archresult.get_metrics(dataset, 'x-test', iepoch=iepoch, is_random=is_random)
      except:
        test__info = None
      try:
        valid_info = archresult.get_metrics(dataset, 'x-valid', iepoch=iepoch, is_random=is_random)
      except:
        valid_info = None
      try:
        est_valid_info = archresult.get_metrics(dataset, 'ori-test', iepoch=iepoch, is_random=is_random)
      except:
        est_valid_info = None
      xifo = {'train-loss'    : train_info['loss'],
              'train-accuracy': train_info['accuracy']}
      if test__info is not None:
        xifo['test-loss'] = test__info['loss'],
        xifo['test-accuracy'] = test__info['accuracy']
      if valid_info is not None:
        xifo['valid-loss'] = valid_info['loss']
        xifo['valid-accuracy'] = valid_info['accuracy']
      if est_valid_info is not None:
        xifo['est-valid-loss'] = est_valid_info['loss']
        xifo['est-valid-accuracy'] = est_valid_info['accuracy']
      return xifo

  """
  This function will print the information of a specific (or all) architecture(s).
  If the index < 0: it will loop for all architectures and print their information one by one.
  else: it will print the information of the 'index'-th archiitecture.
  """
  def show(self, index=-1):
    if index < 0: # show all architectures
      print(self)
      for i, idx in enumerate(self.evaluated_indexes):
        print('\n' + '-' * 10 + ' The ({:5d}/{:5d}) {:06d}-th architecture! '.format(i, len(self.evaluated_indexes), idx) + '-'*10)
        print('arch : {:}'.format(self.meta_archs[idx]))
        strings = print_information(self.arch2infos_full[idx])
        print('>' * 40 + ' {:03d} epochs '.format(self.arch2infos_full[idx].get_total_epoch()) + '>' * 40)
        print('\n'.join(strings))
        strings = print_information(self.arch2infos_less[idx])
        print('>' * 40 + ' {:03d} epochs '.format(self.arch2infos_less[idx].get_total_epoch()) + '>' * 40)
        print('\n'.join(strings))
        print('<' * 40 + '------------' + '<' * 40)
    else:
      if 0 <= index < len(self.meta_archs):
        if index not in self.evaluated_indexes: print('The {:}-th architecture has not been evaluated or not saved.'.format(index))
        else:
          strings = print_information(self.arch2infos_full[index])
          print('>' * 40 + ' {:03d} epochs '.format(self.arch2infos_full[index].get_total_epoch()) + '>' * 40)
          print('\n'.join(strings))
          strings = print_information(self.arch2infos_less[index])
          print('>' * 40 + ' {:03d} epochs '.format(self.arch2infos_less[index].get_total_epoch()) + '>' * 40)
          print('\n'.join(strings))
          print('<' * 40 + '------------' + '<' * 40)
      else:
        print('This index ({:}) is out of range (0~{:}).'.format(index, len(self.meta_archs)))

  # This func shows how to read the string-based architecture encoding
  #   the same as the `str2structure` func in `AutoDL-Projects/lib/models/cell_searchs/genotypes.py`
  # Usage:
  #   arch = api.str2lists( '|nor_conv_1x1~0|+|none~0|none~1|+|none~0|none~1|skip_connect~2|' )
  #   print ('there are {:} nodes in this arch'.format(len(arch)+1)) # arch is a list
  #   for i, node in enumerate(arch):
  #     print('the {:}-th node is the sum of these {:} nodes with op: {:}'.format(i+1, len(node), node))
  @staticmethod
  def str2lists(xstr):
    assert isinstance(xstr, str), 'must take string (not {:}) as input'.format(type(xstr))
    nodestrs = xstr.split('+')
    genotypes = []
    for i, node_str in enumerate(nodestrs):
      inputs = list(filter(lambda x: x != '', node_str.split('|')))
      for xinput in inputs: assert len(xinput.split('~')) == 2, 'invalid input length : {:}'.format(xinput)
      inputs = ( xi.split('~') for xi in inputs )
      input_infos = tuple( (op, int(IDX)) for (op, IDX) in inputs)
      genotypes.append( input_infos )
    return genotypes

  # This func shows how to convert the string-based architecture encoding to the encoding strategy in NAS-Bench-101
  # Usage:
  #   # this will return a numpy matrix (2-D np.array)
  #   matrix = api.str2matrix( '|nor_conv_1x1~0|+|none~0|none~1|+|none~0|none~1|skip_connect~2|' )
  #   # This matrix is 4-by-4 matrix representing a cell with 4 nodes (only the lower left triangle is useful).
  #      [ [0, 0, 0, 0],  # the first line represents the input (0-th) node
  #        [2, 0, 0, 0],  # the second line represents the 1-st node, is calculated by 2-th-op( 0-th-node )
  #        [0, 0, 0, 0],  # the third line represents the 2-nd node, is calculated by 0-th-op( 0-th-node ) + 0-th-op( 1-th-node )
  #        [0, 0, 1, 0] ] # the fourth line represents the 3-rd node, is calculated by 0-th-op( 0-th-node ) + 0-th-op( 1-th-node ) + 1-th-op( 2-th-node )
  #   In NAS-Bench-201 search space, 0-th-op is 'none', 1-th-op is 'skip_connect'
  #      2-th-op is 'nor_conv_1x1', 3-th-op is 'nor_conv_3x3', 4-th-op is 'avg_pool_3x3'.
  @staticmethod
  def str2matrix(xstr):
    assert isinstance(xstr, str), 'must take string (not {:}) as input'.format(type(xstr))
    # this only support NAS-Bench-201 search space
    # this defination will be consistant with this line https://github.com/D-X-Y/AutoDL-Projects/blob/master/lib/models/cell_operations.py#L24
    # If a node has two input-edges from the same node, this function does not work. One edge will be overleaped.
    NAS_BENCH_201         = ['none', 'skip_connect', 'nor_conv_1x1', 'nor_conv_3x3', 'avg_pool_3x3']
    nodestrs = xstr.split('+')
    num_nodes = len(nodestrs) + 1
    matrix = np.zeros((num_nodes,num_nodes))
    for i, node_str in enumerate(nodestrs):
      inputs = list(filter(lambda x: x != '', node_str.split('|')))
      for xinput in inputs: assert len(xinput.split('~')) == 2, 'invalid input length : {:}'.format(xinput)
      for xi in inputs:
        op, idx = xi.split('~')
        if op not in NAS_BENCH_201: raise ValueError('this op ({:}) is not in {:}'.format(op, NAS_BENCH_201))
        op_idx, node_idx = NAS_BENCH_201.index(op), int(idx)
        matrix[i+1, node_idx] = op_idx
    return matrix




class ArchResults(object):

  def __init__(self, arch_index, arch_str):
    self.arch_index   = int(arch_index)
    self.arch_str     = copy.deepcopy(arch_str)
    self.all_results  = dict()
    self.dataset_seed = dict()
    self.clear_net_done = False

  def get_comput_costs(self, dataset):
    x_seeds = self.dataset_seed[dataset]
    results = [self.all_results[ (dataset, seed) ] for seed in x_seeds]

    flops      = [result.flop for result in results]
    params     = [result.params for result in results]
    lantencies = [result.get_latency() for result in results]
    lantencies = [x for x in lantencies if x > 0]
    mean_latency = np.mean(lantencies) if len(lantencies) > 0 else None
    time_infos = defaultdict(list)
    for result in results:
      time_info = result.get_times()
      for key, value in time_info.items(): time_infos[key].append( value )
     
    info = {'flops'  : np.mean(flops),
            'params' : np.mean(params),
            'latency': mean_latency}
    for key, value in time_infos.items():
      if len(value) > 0 and value[0] is not None:
        info[key] = np.mean(value)
      else: info[key] = None
    return info

  """
  This `get_metrics` function is used to obtain obtain the loss, accuracy, etc information on a specific dataset.
  If not specify, each set refer to the proposed split in NAS-Bench-201 paper.
  If some args return None or raise error, then it is not avaliable.
  ========================================
  Args [dataset] (4 possible options):
    -- cifar10-valid : training the model on the CIFAR-10 training set.
    -- cifar10 : training the model on the CIFAR-10 training + validation set.
    -- cifar100 : training the model on the CIFAR-100 training set.
    -- ImageNet16-120 : training the model on the ImageNet16-120 training set.
  Args [setname] (each dataset has different setnames):
    -- When dataset = cifar10-valid, you can use 'train', 'x-valid', 'ori-test'
    ------ 'train' : the metric on the training set.
    ------ 'x-valid' : the metric on the validation set.
    ------ 'ori-test' : the metric on the test set.
    -- When dataset = cifar10, you can use 'train', 'ori-test'.
    ------ 'train' : the metric on the training + validation set.
    ------ 'ori-test' : the metric on the test set.
    -- When dataset = cifar100 or ImageNet16-120, you can use 'train', 'ori-test', 'x-valid', 'x-test'
    ------ 'train' : the metric on the training set.
    ------ 'x-valid' : the metric on the validation set.
    ------ 'x-test' : the metric on the test set.
    ------ 'ori-test' : the metric on the validation + test set.
  Args [iepoch] (None or an integer in [0, the-number-of-total-training-epochs)
    ------ None : return the metric after the last training epoch.
    ------ an integer i : return the metric after the i-th training epoch.
  Args [is_random]:
    ------ True : return the metric of a randomly selected trial.
    ------ False : return the averaged metric of all avaliable trials.
    ------ an integer indicating the 'seed' value : return the metric of a specific trial (whose random seed is 'is_random').
  """
  def get_metrics(self, dataset, setname, iepoch=None, is_random=False):
    x_seeds = self.dataset_seed[dataset]
    results = [self.all_results[ (dataset, seed) ] for seed in x_seeds]
    infos   = defaultdict(list)
    for result in results:
      if setname == 'train':
        info = result.get_train(iepoch)
      else:
        info = result.get_eval(setname, iepoch)
      for key, value in info.items(): infos[key].append( value )
    return_info = dict()
    if isinstance(is_random, bool) and is_random: # randomly select one
      index = random.randint(0, len(results)-1)
      for key, value in infos.items(): return_info[key] = value[index]
    elif isinstance(is_random, bool) and not is_random: # average
      for key, value in infos.items():
        if len(value) > 0 and value[0] is not None:
          return_info[key] = np.mean(value)
        else: return_info[key] = None
    elif isinstance(is_random, int): # specify the seed
      if is_random not in x_seeds: raise ValueError('can not find random seed ({:}) from {:}'.format(is_random, x_seeds))
      index = x_seeds.index(is_random)
      for key, value in infos.items(): return_info[key] = value[index]
    else:
      raise ValueError('invalid value for is_random: {:}'.format(is_random))
    return return_info

  def show(self, is_print=False):
    return print_information(self, None, is_print)

  def get_dataset_names(self):
    return list(self.dataset_seed.keys())

  def get_dataset_seeds(self, dataset):
    return copy.deepcopy( self.dataset_seed[dataset] )

  """
  This function will return the trained network's weights on the 'dataset'.
  When the 'seed' is None, it will return the weights for every run trial in the form of a dict.
  When the 
  """
  def get_net_param(self, dataset, seed=None):
    if seed is None:
      x_seeds = self.dataset_seed[dataset]
      return {seed: self.all_results[(dataset, seed)].get_net_param() for seed in x_seeds}
    else:
      return self.all_results[(dataset, seed)].get_net_param()

  # get the total number of training epochs
  def get_total_epoch(self, dataset=None):
    if dataset is None:
      epochss = []
      for xdata, x_seeds in self.dataset_seed.items():
        epochss += [self.all_results[(xdata, seed)].get_total_epoch() for seed in x_seeds]
    elif isinstance(dataset, str):
      x_seeds = self.dataset_seed[dataset]
      epochss = [self.all_results[(dataset, seed)].get_total_epoch() for seed in x_seeds]
    else:
      raise ValueError('invalid dataset={:}'.format(dataset))
    if len(set(epochss)) > 1: raise ValueError('Each trial mush have the same number of training epochs : {:}'.format(epochss))
    return epochss[-1]

  # return the ResultsCount object (containing all information of a single trial) for 'dataset' and 'seed'
  def query(self, dataset, seed=None):
    if seed is None:
      x_seeds = self.dataset_seed[dataset]
      return {seed: self.all_results[ (dataset, seed) ] for seed in x_seeds}
    else:
      return self.all_results[ (dataset, seed) ]

  def arch_idx_str(self):
    return '{:06d}'.format(self.arch_index)

  def update(self, dataset_name, seed, result):
    if dataset_name not in self.dataset_seed:
      self.dataset_seed[dataset_name] = []
    assert seed not in self.dataset_seed[dataset_name], '{:}-th arch alreadly has this seed ({:}) on {:}'.format(self.arch_index, seed, dataset_name)
    self.dataset_seed[ dataset_name ].append( seed )
    self.dataset_seed[ dataset_name ] = sorted( self.dataset_seed[ dataset_name ] )
    assert (dataset_name, seed) not in self.all_results
    self.all_results[ (dataset_name, seed) ] = result
    self.clear_net_done = False

  def state_dict(self):
    state_dict = dict()
    for key, value in self.__dict__.items():
      if key == 'all_results': # contain the class of ResultsCount
        xvalue = dict()
        assert isinstance(value, dict), 'invalid type of value for {:} : {:}'.format(key, type(value))
        for _k, _v in value.items():
          assert isinstance(_v, ResultsCount), 'invalid type of value for {:}/{:} : {:}'.format(key, _k, type(_v))
          xvalue[_k] = _v.state_dict()
      else:
        xvalue = value
      state_dict[key] = xvalue
    return state_dict

  def load_state_dict(self, state_dict):
    new_state_dict = dict()
    for key, value in state_dict.items():
      if key == 'all_results': # to convert to the class of ResultsCount
        xvalue = dict()
        assert isinstance(value, dict), 'invalid type of value for {:} : {:}'.format(key, type(value))
        for _k, _v in value.items():
          xvalue[_k] = ResultsCount.create_from_state_dict(_v)
      else: xvalue = value
      new_state_dict[key] = xvalue
    self.__dict__.update(new_state_dict)

  @staticmethod
  def create_from_state_dict(state_dict_or_file):
    x = ArchResults(-1, -1)
    if isinstance(state_dict_or_file, str): # a file path
      state_dict = torch.load(state_dict_or_file)
    elif isinstance(state_dict_or_file, dict):
      state_dict = state_dict_or_file
    else:
      raise ValueError('invalid type of state_dict_or_file : {:}'.format(type(state_dict_or_file)))
    x.load_state_dict(state_dict)
    return x

  # This function is used to clear the weights saved in each 'result'
  # This can help reduce the memory footprint.
  def clear_params(self):
    for key, result in self.all_results.items():
      result.net_state_dict = None
    self.clear_net_done = True 

  def __repr__(self):
    return ('{name}(arch-index={index}, arch={arch}, {num} runs, clear={clear})'.format(name=self.__class__.__name__, index=self.arch_index, arch=self.arch_str, num=len(self.all_results), clear=self.clear_net_done))
    


"""
This class (ResultsCount) is used to save the information of one trial for a single architecture.
I did not write much comment for this class, because it is the lowest-level class in NAS-Bench-201 API, which will be rarely called.
If you have any question regarding this class, please open an issue or email me.
"""
class ResultsCount(object):

  def __init__(self, name, state_dict, train_accs, train_losses, params, flop, arch_config, seed, epochs, latency):
    self.name           = name
    self.net_state_dict = state_dict
    self.train_acc1es = copy.deepcopy(train_accs)
    self.train_acc5es = None
    self.train_losses = copy.deepcopy(train_losses)
    self.train_times  = None
    self.arch_config  = copy.deepcopy(arch_config)
    self.params     = params
    self.flop       = flop
    self.seed       = seed
    self.epochs     = epochs
    self.latency    = latency
    # evaluation results
    self.reset_eval()

  def update_train_info(self, train_acc1es, train_acc5es, train_losses, train_times):
    self.train_acc1es = train_acc1es
    self.train_acc5es = train_acc5es
    self.train_losses = train_losses
    self.train_times  = train_times

  def reset_eval(self):
    self.eval_names  = []
    self.eval_acc1es = {}
    self.eval_times  = {}
    self.eval_losses = {}

  def update_latency(self, latency):
    self.latency = copy.deepcopy( latency )

  def update_eval(self, accs, losses, times):  # new version
    data_names = set([x.split('@')[0] for x in accs.keys()])
    for data_name in data_names:
      assert data_name not in self.eval_names, '{:} has already been added into eval-names'.format(data_name)
      self.eval_names.append( data_name )
      for iepoch in range(self.epochs):
        xkey = '{:}@{:}'.format(data_name, iepoch)
        self.eval_acc1es[ xkey ] = accs[ xkey ]
        self.eval_losses[ xkey ] = losses[ xkey ]
        self.eval_times [ xkey ] = times[ xkey ]

  def update_OLD_eval(self, name, accs, losses): # old version
    assert name not in self.eval_names, '{:} has already added'.format(name)
    self.eval_names.append( name )
    for iepoch in range(self.epochs):
      if iepoch in accs:
        self.eval_acc1es['{:}@{:}'.format(name,iepoch)] = accs[iepoch]
        self.eval_losses['{:}@{:}'.format(name,iepoch)] = losses[iepoch]

  def __repr__(self):
    num_eval = len(self.eval_names)
    set_name = '[' + ', '.join(self.eval_names) + ']'
    return ('{name}({xname}, arch={arch}, FLOP={flop:.2f}M, Param={param:.3f}MB, seed={seed}, {num_eval} eval-sets: {set_name})'.format(name=self.__class__.__name__, xname=self.name, arch=self.arch_config['arch_str'], flop=self.flop, param=self.params, seed=self.seed, num_eval=num_eval, set_name=set_name))

  # get the total number of training epochs
  def get_total_epoch(self):
    return copy.deepcopy(self.epochs)
  
  # get the latency
  # -1 represents not avaliable ; otherwise it should be a float value
  def get_latency(self):
    if self.latency is None: return -1
    else: return sum(self.latency) / len(self.latency)

  # get the information regarding time
  def get_times(self):
    if self.train_times is not None and isinstance(self.train_times, dict):
      train_times = list( self.train_times.values() )
      time_info = {'T-train@epoch': np.mean(train_times), 'T-train@total': np.sum(train_times)}
      for name in self.eval_names:
        xtimes = [self.eval_times['{:}@{:}'.format(name,i)] for i in range(self.epochs)]
        time_info['T-{:}@epoch'.format(name)] = np.mean(xtimes)
        time_info['T-{:}@total'.format(name)] = np.sum(xtimes)
    else:
      time_info = {'T-train@epoch':                 None, 'T-train@total':               None }
      for name in self.eval_names:
        time_info['T-{:}@epoch'.format(name)] = None
        time_info['T-{:}@total'.format(name)] = None
    return time_info

  def get_eval_set(self):
    return self.eval_names

  # get the training information
  def get_train(self, iepoch=None):
    if iepoch is None: iepoch = self.epochs-1
    assert 0 <= iepoch < self.epochs, 'invalid iepoch={:} < {:}'.format(iepoch, self.epochs)
    if self.train_times is not None:
      xtime = self.train_times[iepoch]
      atime = sum([self.train_times[i] for i in range(iepoch+1)])
    else: xtime, atime = None, None
    return {'iepoch'  : iepoch,
            'loss'    : self.train_losses[iepoch],
            'accuracy': self.train_acc1es[iepoch],
            'cur_time': xtime,
            'all_time': atime}

  # get the evaluation information ; there could be multiple evaluation sets (identified by the 'name' argument).
  def get_eval(self, name, iepoch=None):
    if iepoch is None: iepoch = self.epochs-1
    assert 0 <= iepoch < self.epochs, 'invalid iepoch={:} < {:}'.format(iepoch, self.epochs)
    if isinstance(self.eval_times,dict) and len(self.eval_times) > 0:
      xtime = self.eval_times['{:}@{:}'.format(name,iepoch)]
      atime = sum([self.eval_times['{:}@{:}'.format(name,i)] for i in range(iepoch+1)])
    else: xtime, atime = None, None
    return {'iepoch'  : iepoch,
            'loss'    : self.eval_losses['{:}@{:}'.format(name,iepoch)],
            'accuracy': self.eval_acc1es['{:}@{:}'.format(name,iepoch)],
            'cur_time': xtime,
            'all_time': atime}

  def get_net_param(self):
    return self.net_state_dict

  # This function is used to obtain the config dict for this architecture.
  def get_config(self, str2structure):
    if str2structure is None:
      return {'name': 'infer.tiny', 'C': self.arch_config['channel'], \
              'N'   : self.arch_config['num_cells'], \
              'arch_str': self.arch_config['arch_str'], 'num_classes': self.arch_config['class_num']}
    else:
      return {'name': 'infer.tiny', 'C': self.arch_config['channel'], \
              'N'   : self.arch_config['num_cells'], \
              'genotype': str2structure(self.arch_config['arch_str']), 'num_classes': self.arch_config['class_num']}

  def state_dict(self):
    _state_dict = {key: value for key, value in self.__dict__.items()}
    return _state_dict

  def load_state_dict(self, state_dict):
    self.__dict__.update(state_dict)

  @staticmethod
  def create_from_state_dict(state_dict):
    x = ResultsCount(None, None, None, None, None, None, None, None, None, None)
    x.load_state_dict(state_dict)
    return x
