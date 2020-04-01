# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors and The HuggingFace Inc. team.
# Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
""" Finetuning the library models for sequence classification on GLUE (Bert, XLM, XLNet, RoBERTa)."""

from __future__ import absolute_import, division, print_function

import argparse
import glob
import logging
import os
import random
import sys 

import numpy as np
import torch
from torch.utils.data import (DataLoader, RandomSampler, SequentialSampler,
                              TensorDataset)
from torch.utils.data.distributed import DistributedSampler

try:
    from torch.utils.tensorboard import SummaryWriter
except:
    from tensorboardX import SummaryWriter

from tqdm import tqdm, trange
from knockknock import slack_sender
import networkx as nx



from transformers import (WEIGHTS_NAME, BertConfig,
                                  BertForSequenceClassification, BertTokenizer,
                                  RobertaConfig,
                                  RobertaForSequenceClassification,
                                  RobertaTokenizer,
                                  XLMConfig, XLMForSequenceClassification,
                                  XLMTokenizer, XLNetConfig,
                                  XLNetForSequenceClassification,
                                  XLNetTokenizer,
                                  DistilBertConfig,
                                  DistilBertForSequenceClassification,
                                  DistilBertTokenizer,
                                  AlbertConfig,
                                  AlbertForSequenceClassification, 
                                  AlbertTokenizer,
                                )
from extra_layers_2 import (GraphConvClassification,
                                  BertForNodeEmbedding,
                                  NoGraphClassification
                                  #RobertaForRelationClassification,
                                  #RobertaForNodeEmbedding,
                                )
print(type(BertConfig))
from transformers import AdamW, get_linear_schedule_with_warmup
#from utils_relation import *
from utils_relation import glue_compute_metrics as compute_metrics
from utils_relation import glue_output_modes as output_modes
from utils_relation import glue_processors as processors
from utils_relation import graph_convert_examples_to_features as convert_examples_to_features
from utils_relation import sb_convert_examples_to_features as convert_examples_to_features2

logger = logging.getLogger(__name__)

ALL_MODELS = sum((tuple(conf.pretrained_config_archive_map.keys()) for conf in (BertConfig, XLNetConfig, XLMConfig, 
                                                                                RobertaConfig, DistilBertConfig)), ())

MODEL_CLASSES = {
    'bert': (BertConfig, BertForSequenceClassification, BertTokenizer),
    'xlnet': (XLNetConfig, XLNetForSequenceClassification, XLNetTokenizer),
    'xlm': (XLMConfig, XLMForSequenceClassification, XLMTokenizer),
    'roberta': (RobertaConfig, RobertaForSequenceClassification, RobertaTokenizer),
    'distilbert': (DistilBertConfig, DistilBertForSequenceClassification, DistilBertTokenizer),
    'albert': (AlbertConfig, AlbertForSequenceClassification, AlbertTokenizer)
}

GRAPH_CLASSES = {
    #'bert': (BertConfig, GraphConvClassification, BertTokenizer, BertForNodeEmbedding),
    'bert': (BertConfig, NoGraphClassification, BertTokenizer, BertForNodeEmbedding),
    #'roberta': (RobertaConfig, RobertaForRelationClassification, RobertaTokenizer, RobertaForNodeEmbedding)
}


def set_seed(args):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.n_gpu > 0:
        torch.cuda.manual_seed_all(args.seed)


def train(args, dataset, model, classifier,  tokenizer, eval_dataset=None):#conv_graph
    """ Train the model """
    if args.local_rank in [-1, 0]:
        tb_writer = SummaryWriter()

    #results = evaluate(args, eval_dataset, model, classifier, tokenizer)#conv_graph, 

    all_input_ids, all_attention_masks, all_token_type_ids,adjacency_matrixs,relation_lists=dataset
    #print('training dataset: ',len(train_dataset), len(train_dataset[0]), train_dataset[0][0].size())
    #(181, 3, [650, 128])
    #(doc, (input_msk, att_msk, token_type), [node, seq_len])
    #print('adj dataset: ',len(adjacency_matrixs), len(adjacency_matrixs[0]))
    #(181,[[132,132]])
    #print('relation dataset: ',len(relation_lists), len(relation_lists[0]), len(relation_lists[0][0]))
    #(181, 154(#relations), 3)
    args.train_batch_size = args.per_gpu_train_batch_size * max(1, args.n_gpu)
    #train_sampler = RandomSampler(train_dataset) if args.local_rank == -1 else DistributedSampler(train_dataset)
    #train_dataloader = DataLoader(train_dataset, shuffle=False, batch_size=1) # sampler=train_sampler,
    #train_adjacency_matrix = DataLoader(adjacency_matrixs, sampler=train_sampler, batch_size=1)
    #train_relation_list = DataLoader(relation_lists, sampler=train_sampler, batch_size=1)

    # each relation list: [(0,1,overlap), (1,2,before), (7,8,after)]
    # each adjacency matrix: [[1,1,0,0],[1,0,0,0],[0,0,1,0],[0,0,0,1]]
    # TODO: read adjacency matrix and relation list and then using the same sampler to shuffle it

    t_total = 10000
    '''
    if args.max_steps > 0:
        t_total = args.max_steps
        args.num_train_epochs = args.max_steps // (len(train_dataloader) // args.gradient_accumulation_steps) + 1
    else:
        t_total = len(train_dataloader) // args.gradient_accumulation_steps * args.num_train_epochs
    '''
    #for n,p in model.named_parameters(): print(n)
    # Prepare optimizer and schedule (linear warmup and decay)
    no_decay = ['bias', 'LayerNorm.weight']
    # fine tune only the last three layers and pooler
    lst_n = ['bert.encoder.layer.'+ str(11-i) for i in range(args.n_layer)] + ['bert.pooler']
    #print("Bert layer that are being trained: ",lst_n)
    optimizer_grouped_parameters = [
        {'params': [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)  ], 'weight_decay': args.weight_decay},#and any(n.startswith(ln) for ln in lst_n))
        {'params': [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay) ], 'weight_decay': 0.0},#and any(n.startswith(ln) for ln in lst_n))
        {'params': [p for n, p in classifier.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': args.weight_decay},
        {'params': [p for n, p in classifier.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0},
        #{'params': [p for n, p in conv_graph.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': args.weight_decay},
        #{'params': [p for n, p in conv_graph.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
        ]

    optimizer = AdamW(optimizer_grouped_parameters, lr=args.learning_rate, eps=args.adam_epsilon)
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=args.warmup_steps, num_training_steps=np.ceil(543*160/args.per_gpu_train_batch_size))

    if args.fp16:
        try:
            from apex import amp
        except ImportError:
            raise ImportError("Please install apex from https://www.github.com/nvidia/apex to use fp16 training.")
        model, optimizer = amp.initialize(model, optimizer, opt_level=args.fp16_opt_level)

    # multi-gpu training (should be after apex fp16 initialization)
    if args.n_gpu > 1:
        model = torch.nn.DataParallel(model)

    # Distributed training (should be after apex fp16 initialization)
    if args.local_rank != -1:
        model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[args.local_rank],
                                                          output_device=args.local_rank,
                                                          find_unused_parameters=True)

    # Train!
    logger.info("***** Running training *****")
    #logger.info("  Num examples = %d", len(train_dataset))
    logger.info("  Num Epochs = %d", args.num_train_epochs)
    logger.info("  Instantaneous batch size per GPU = %d", args.per_gpu_train_batch_size)
    logger.info("  Total train batch size (w. parallel, distributed & accumulation) = %d",
                   args.train_batch_size * args.gradient_accumulation_steps * (torch.distributed.get_world_size() if args.local_rank != -1 else 1))
    logger.info("  Gradient Accumulation steps = %d", args.gradient_accumulation_steps)
    logger.info("  Total optimization steps = %d", t_total)

    global_step = 0
    tr_loss, logging_loss = 0.0, 0.0
    #for n, p in model.named_parameters():
        #if not any( n.startswith(ln) for ln in lst_n):
        #p.requires_grad = False
    model.zero_grad()
    classifier.zero_grad()
    #conv_graph.zero_grad()
    #train_iterator = trange(int(1), desc="Epoch", disable=args.local_rank not in [-1, 0])#args.num_train_epochs
    set_seed(args)  # Added here for reproductibility (even between python 2 and 3)
    for _ in range(1):
        #epoch_iterator = tqdm(train_dataloader, desc="Iteration", disable=args.local_rank not in [-1, 0])
        for step in range(181):
            model.train()  
            #conv_graph.train()  
            classifier.train()  

                      
            #batch = tuple(t.to(args.device) for t in batch)
            #batch = change_shape(batch)

            PSL_dataset = build_super_dataset(rel = relation_lists[step], batch = (all_input_ids[step], all_attention_masks[step], all_token_type_ids[step]))
            #print("relations: ",relation_lists[step])
            #PSL_dataset, dense_adj = build_PSL_dataset(adj = np.array(adjacency_matrixs[step]), rel = relation_lists[step])
            # relation_dataset = build_relation_dataset(relation_lists[step]) #train_relation_lists
            # (batch_size,[e1,e2]), (batch_size, rel)
            relation_train_sampler = SequentialSampler(PSL_dataset) if args.local_rank == -1 else DistributedSampler(relation_dataset)
            relation_train_dataloader = DataLoader(PSL_dataset, sampler=relation_train_sampler, batch_size=args.train_batch_size*4)
            relation_epoch_iterator = tqdm(relation_train_dataloader, desc="Iteration", disable=args.local_rank not in [-1, 0])

            for step2, rel_batch in enumerate(relation_epoch_iterator):
                #adjacency_matrix = dense_adj
                adjacency_matrix = np.array(adjacency_matrixs[step])
                #g = nx.from_numpy_matrix(adjacency_matrix)
                #print(g.number_of_edges())
                #adjacency_matrix = neiAdj(adj = adjacency_matrix)
                #neighbors = find_neighbors(rel_batch[0] ,adjacency_matrix, order = 2,thres = 650).astype(int)
                #print("# neighboring nodes: ",neighbors.shape)
                # reconstruct index
                #temp_rel = np.array(rel_batch[0].cpu())
                #print("rel_batch size: ",temp_rel)
                #rel_batch[0] = torch.tensor([[int(np.where(neighbors==x)[0]) for x in temp_rel[i]] for i in range(temp_rel.shape[0])])
                rel_batch[0].cuda()
                #print("rel_batch: ",rel_batch[0])
                #adjacency_matrix = adjacency_matrix[neighbors, :][:, neighbors]
                # change batch to be size of ( node_size,3, seq_len)
                # print('before batch size: ',len(batch),len(batch[0]), batch[0][0].size() )

                #mini_batch = rel_batch[2]#[neighbors]
                #print("batch: ", len(mini_batch))
                #print("adj, ", adjacency_matrix.shape)
                #print("rel_batch: ", rel_batch[0].size())
                # print('after batch size: ', batch.size() )
                inputs = {'input_ids': rel_batch[2], 
                        'attention_mask': rel_batch[3]}
 
                if args.model_type != 'distilbert':
                    inputs['token_type_ids'] = rel_batch[4] if args.model_type in ['bert', 'xlnet'] else None  # XLM, DistilBERT and RoBERTa don't use segment_ids'''
                #print("inputs", inputs)
                node_embeddings = model(**inputs) # outputs should be a floattensor list which are nodes embeddings
                #output = output.detach().cpu()

                inputs = {'adjacency_matrix':  adjacency_matrix,
                        'node_embeddings' : node_embeddings,
                        'idx': rel_batch[0],
                        'label': rel_batch[1]}

                outputs = classifier(**inputs)
                '''
                for name, param in classifier.named_parameters():
                    if name == 'Graphmodel.weight':# or name == 'classifier.weight':
                        print('Graph: ', param[0][0])
                    if name == 'classifier.weight':
                        print("classifier: ", param[0][0])
                '''
                loss,_ = outputs  # model outputs are always tuple in transformers (see doc)
                

                if args.n_gpu > 1:
                    loss = loss.mean() # mean() to average on multi-gpu parallel training
                if args.gradient_accumulation_steps > 1:
                    loss = loss / args.gradient_accumulation_steps

                if args.fp16:
                    with amp.scale_loss(loss, optimizer) as scaled_loss:
                        scaled_loss.backward()
                else:
                    loss.backward()


                tr_loss += loss.item()

                if (step2 + 1) % args.gradient_accumulation_steps == 0:
                    if args.fp16:
                        torch.nn.utils.clip_grad_norm_(amp.master_params(optimizer), args.max_grad_norm)
                    else:
                        torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                        torch.nn.utils.clip_grad_norm_(classifier.parameters(), args.max_grad_norm)
                        #torch.nn.utils.clip_grad_norm_(conv_graph.parameters(), args.max_grad_norm)

                    optimizer.step()
                    scheduler.step()  # Update learning rate schedule
                    model.zero_grad()                    
                    classifier.zero_grad()
                    #conv_graph.zero_grad()
                    global_step += 1

                    if args.do_eval and args.local_rank in [-1, 0] and args.logging_steps > 0 and global_step % args.logging_steps == 0:
                        # Log metrics
                        if args.local_rank == -1 and args.evaluate_during_training:  # Only evaluate when single GPU otherwise metrics may not average well
                            #logger.info("$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$")
                            results = evaluate(args, eval_dataset, model, classifier, tokenizer)#conv_graph, 
                            #for key, value in results.items():
                                #tb_writer.add_scalar('eval_{}'.format(key), value, global_step)
                        tb_writer.add_scalar('lr', scheduler.get_lr()[0], global_step)
                        tb_writer.add_scalar('loss', (tr_loss - logging_loss)/args.logging_steps, global_step)
                        logging_loss = tr_loss

                    if args.local_rank in [-1, 0] and args.save_steps > 0 and global_step % args.save_steps == 0:
                        # Save model checkpoint
                        output_dir = os.path.join(args.output_dir, 'checkpoint-{}'.format(global_step))
                        if not os.path.exists(output_dir):
                            os.makedirs(output_dir)
                        model_to_save = model.module if hasattr(model, 'module') else model  # Take care of distributed/parallel training
                        model_to_save.save_pretrained(output_dir)
                        torch.save(args, os.path.join(output_dir, 'training_args.bin'))
                        logger.info("Saving model checkpoint to %s", output_dir)

                if args.max_steps > 0 and global_step > args.max_steps:
                    epoch_iterator.close()
                    break
        if args.max_steps > 0 and global_step > args.max_steps:
            # TODO: early stopping
            train_iterator.close()
            break

        #evaluate(args, eval_dataset, model, classifier, conv_graph, tokenizer)

    if args.local_rank in [-1, 0]:
        tb_writer.close()

    return global_step, tr_loss / global_step



def evaluate(args, dataset, model, classifier,  tokenizer, prefix=""):#conv_gragh
    """ evaluate the model """
    results={}
    eval_output_dir = args.output_dir
    all_input_ids, all_attention_masks, all_token_type_ids,adjacency_matrixs,relation_lists=dataset
    #eval_dataset,adjacency_matrixs,relation_lists=dataset
    args.train_batch_size = args.per_gpu_train_batch_size * max(1, args.n_gpu)
    #eval_sampler = RandomSampler(eval_dataset) if args.local_rank == -1 else DistributedSampler(eval_dataset)
    #eval_dataloader = DataLoader(eval_dataset, shuffle=False, batch_size=1) # sampler=eval_sampler,
    # eval_adjacency_matrix = DataLoader(adjacency_matrixs, sampler=eval_sampler, batch_size=1)
    # eval_relation_list = DataLoader(relation_lists, sampler=eval_sampler, batch_size=1)
    
    # eval_adjacency_matrixs = []
    # for m in eval_adjacency_matrix: eval_adjacency_matrixs.append(m)
    # eval_relation_lists = []
    # for r in eval_relation_list: eval_relation_lists.append(m)

    # Evaluate!
    logger.info("***** Running Evaluation *****")
    #logger.info("  Num examples = %d", len(eval_dataset))
    #logger.info("  Batch size = %d", args.per_gpu_eval_batch_size)

    set_seed(args)  # Added here for reproductibility (even between python 2 and 3)
    #epoch_iterator = tqdm(eval_dataloader, desc="Iteration", disable=args.local_rank not in [-1, 0])
    eval_loss = 0.0
    nb_eval_steps = 0
    preds = None
    out_label_ids = None
    for step in range(len(relation_lists)):
        
        model.eval()
        classifier.eval()
        #conv_graph.eval()
        # change batch to be size of ( node_size,3, seq_len)
        # print('before batch size: ',len(batch),len(batch[0]), batch[0][0].size() )
        

        
        PSL_dataset = build_super_dataset(rel = relation_lists[step], batch = (all_input_ids[step], all_attention_masks[step], all_token_type_ids[step]))
        relation_train_sampler = SequentialSampler(PSL_dataset) if args.local_rank == -1 else DistributedSampler(relation_dataset)
        relation_train_dataloader = DataLoader(PSL_dataset, sampler=relation_train_sampler, batch_size=args.train_batch_size*4)
        relation_epoch_iterator = tqdm(relation_train_dataloader, desc="Iteration", disable=args.local_rank not in [-1, 0])
        
        outputs = []
        with torch.no_grad():
            for step2, rel_batch in enumerate(relation_epoch_iterator):
                adjacency_matrix = np.array(adjacency_matrixs[step])
                rel_batch[0].cuda()

                #mini_batch = rel_batch[2]#[neighbors]
                inputs = {'input_ids': rel_batch[2], 
                        'attention_mask': rel_batch[3]}

                if args.model_type != 'distilbert':
                    inputs['token_type_ids'] = rel_batch[4] if args.model_type in ['bert', 'xlnet'] else None  # XLM, DistilBERT and RoBERTa don't use segment_ids'''
                node_embeddings = model(**inputs) # outputs should be a floattensor list which are nodes embeddings

                inputs = {'adjacency_matrix':  adjacency_matrix,
                        'node_embeddings' : node_embeddings,
                        'idx': rel_batch[0],
                        'label': rel_batch[1],
                        'cal_hidden_loss': False}

                outputs = classifier(**inputs)
                tmp_eval_loss,logits = outputs  
                eval_loss += tmp_eval_loss.mean().item()

                nb_eval_steps += 1
                if preds is None:
                    preds = logits.detach().cpu().numpy()
                    out_label_ids = inputs['label'].detach().cpu().numpy()
                else:
                    preds = np.append(preds, logits.detach().cpu().numpy(), axis=0)
                    out_label_ids = np.append(out_label_ids, inputs['label'].detach().cpu().numpy(), axis=0)

    eval_loss = eval_loss / nb_eval_steps
    preds_max = np.argmax(preds, axis=1)
    result = compute_metrics(args.task_name, preds_max, out_label_ids)
    results.update(result)

    output_eval_file = os.path.join(eval_output_dir, prefix, "eval_results.txt")
    with open(output_eval_file, "w") as writer:
        logger.info("***** Eval results {} *****".format(prefix))
        for key in sorted(result.keys()):
            logger.info("  %s = %s", key, str(result[key]))
            writer.write("%s = %s\n" % (key, str(result[key])))

    return results


# def evaluate2(args, model, tokenizer, prefix=""):
#     # Loop to handle MNLI double evaluation (matched, mis-matched)
#     eval_task_names = ("mnli", "mnli-mm") if args.task_name == "mnli" else (args.task_name,)
#     eval_outputs_dirs = (args.output_dir, args.output_dir + '-MM') if args.task_name == "mnli" else (args.output_dir,)

#     results = {}
#     for eval_task, eval_output_dir in zip(eval_task_names, eval_outputs_dirs):
#         eval_dataset = load_and_cache_examples(args, eval_task, tokenizer, evaluate=True)

#         if not os.path.exists(eval_output_dir) and args.local_rank in [-1, 0]:
#             os.makedirs(eval_output_dir)

#         args.eval_batch_size = args.per_gpu_eval_batch_size * max(1, args.n_gpu)
#         # Note that DistributedSampler samples randomly
#         eval_sampler = SequentialSampler(eval_dataset) if args.local_rank == -1 else DistributedSampler(eval_dataset)
#         eval_dataloader = DataLoader(eval_dataset, sampler=eval_sampler, batch_size=args.eval_batch_size)

#         # multi-gpu eval
#         if args.n_gpu > 1:
#             model = torch.nn.DataParallel(model)

#         # Eval!
#         logger.info("***** Running evaluation {} *****".format(prefix))
#         logger.info("  Num examples = %d", len(eval_dataset))
#         logger.info("  Batch size = %d", args.eval_batch_size)
#         eval_loss = 0.0
#         nb_eval_steps = 0
#         preds = None
#         out_label_ids = None
#         for batch in tqdm(eval_dataloader, desc="Evaluating"):
#             model.eval()
#             batch = tuple(t.to(args.device) for t in batch)

#             with torch.no_grad():
#                 inputs = {'input_ids':      batch[0],
#                           'attention_mask': batch[1],
#                           'labels':         batch[3]}
#                 if args.model_type != 'distilbert':
#                     inputs['token_type_ids'] = batch[2] if args.model_type in ['bert', 'xlnet'] else None  # XLM, DistilBERT and RoBERTa don't use segment_ids
#                 outputs = model(**inputs)
#                 tmp_eval_loss, logits = outputs[:2]

#                 eval_loss += tmp_eval_loss.mean().item()
#             nb_eval_steps += 1
#             if preds is None:
#                 preds = logits.detach().cpu().numpy()
#                 out_label_ids = inputs['labels'].detach().cpu().numpy()
#             else:
#                 preds = np.append(preds, logits.detach().cpu().numpy(), axis=0)
#                 out_label_ids = np.append(out_label_ids, inputs['labels'].detach().cpu().numpy(), axis=0)

#         eval_loss = eval_loss / nb_eval_steps
#         if args.output_mode == "classification":
#             preds = np.argmax(preds, axis=1)
#         elif args.output_mode == "regression":
#             preds = np.squeeze(preds)
#         result = compute_metrics(eval_task, preds, out_label_ids)
#         results.update(result)

#         output_eval_file = os.path.join(eval_output_dir, prefix, "eval_results.txt")
#         with open(output_eval_file, "w") as writer:
#             logger.info("***** Eval results {} *****".format(prefix))
#             for key in sorted(result.keys()):
#                 logger.info("  %s = %s", key, str(result[key]))
#                 writer.write("%s = %s\n" % (key, str(result[key])))

#     return results


def load_and_cache_examples(args, task, tokenizer, evaluate=False):
    if args.local_rank not in [-1, 0] and not evaluate:
        torch.distributed.barrier()  # Make sure only the first process in distributed training process the dataset, and the others will use the cache

    processor = processors[task]()
    output_mode = output_modes[task]
    # Load data features from cache or dataset file
    cached_features_file = os.path.join(args.data_dir, 'cached_{}_{}_{}_{}'.format(
        'dev' if evaluate else 'train',
        list(filter(None, args.model_name_or_path.split('/'))).pop(),
        str(args.max_seq_length),
        str(task)))
    if False:#os.path.exists(cached_features_file) and not args.overwrite_cache:
        logger.info("Loading features from cached file %s", cached_features_file)
        features = torch.load(cached_features_file)
    else:
        logger.info("Creating features from dataset file at %s", args.data_dir)
        label_list = processor.get_labels()

        examples = processor.get_dev_examples(args.data_dir) if evaluate else processor.get_train_examples(args.data_dir)
        print()
        if evaluate:
            features = convert_examples_to_features(examples,
                                        tokenizer,
                                        label_list=label_list,
                                        max_length=args.max_seq_length,
                                        output_mode=output_mode,
                                        pad_on_left=bool(args.model_type in ['xlnet']),                 # pad on the left for xlnet
                                        pad_token=tokenizer.convert_tokens_to_ids([tokenizer.pad_token])[0],
                                        pad_token_segment_id=4 if args.model_type in ['xlnet'] else 0,
            )
        else:
            features = convert_examples_to_features2(examples,
                                                    tokenizer,
                                                    label_list=label_list,
                                                    max_length=args.max_seq_length,
                                                    output_mode=output_mode,
                                                    pad_on_left=bool(args.model_type in ['xlnet']),                 # pad on the left for xlnet
                                                    pad_token=tokenizer.convert_tokens_to_ids([tokenizer.pad_token])[0],
                                                    pad_token_segment_id=4 if args.model_type in ['xlnet'] else 0,
            )
        # features are composed of documents
        # each document has list of input_ids, doc_id, matrix, list of relations
        if args.local_rank in [-1, 0]:
            logger.info("Saving features into cached file %s", cached_features_file)
            torch.save(features, cached_features_file)

    if args.local_rank == 0 and not evaluate:
        torch.distributed.barrier()  # Make sure only the first process in distributed training process the dataset, and the others will use the cache

    # Convert to Tensors and build dataset
            
    #print(len(features[0].input_ids))
    #print(len(features[1].input_ids))
    #print(len(features[0].input_ids[1]))
    
    #all_input_ids = [[f for f in feature.input_ids] for feature in features]
    #all_attention_mask = [[f for f in feature.attention_masks] for feature in features]
    #all_token_type_ids = [[f for f in feature.token_type_ids] for feature in features]
    all_input_ids = [feature.input_ids for feature in features]
    all_attention_mask = [ feature.attention_masks for feature in features]
    all_token_type_ids = [feature.token_type_ids for feature in features]
    all_matrix = [feature.matrix for feature in features]
    all_relation = [feature.relations for feature in features]
    '''
    print(all_relation[0])
    for i in range(int(len(all_relation[0])/2)):
        print(all_relation[0][i*2][2], all_relation[0][i*2+1][2])
    exit()'''

    logger.info("all_input_ids: %s" % str(len(all_input_ids[0])))
    logger.info("all_attention_mask: %s" % str(len(all_attention_mask[0])))
    logger.info("all_token_type_ids: %s" % str(len(all_token_type_ids[0])))

    logger.info("matrix example size: %s" % str(np.shape(all_matrix[0])))
    logger.info("relation example: %s" % str(np.array(all_relation[0][:3])))

    # if output_mode == "classification":
    #     all_labels = torch.tensor([f.label for f in features], dtype=torch.long)
    # elif output_mode == "regression":
    #     all_labels = torch.tensor([f.label for f in features], dtype=torch.float)
 
    dataset = (all_input_ids, all_attention_mask, all_token_type_ids,all_matrix,all_relation)
    return dataset

def build_relation_dataset(relations):
    embeds = []
    labels = []
    for [e1,e2,r] in relations:
        #relation_dataset.append([[emb1[i]+emb2[i] for i in range(len(emb1))], r])
        labels.append(r)
        embeds.append(torch.tensor([e1,e2]))

    all_inputs = torch.stack(embeds).cuda()
    all_labels = torch.tensor(labels,dtype=torch.long).cuda()   
    #logger.info("relation dataset node embedding size: %s" % str(all_inputs.size()))
    relation_dataset = TensorDataset(all_inputs, all_labels)

    return relation_dataset


def change_shape(batch):
    # changing shape to adapte the size requirement
    in_dim = batch[0][0].size()[0]
    batch = list(batch)
    for index, sbatch in enumerate(batch):
        batch[index] = sbatch[0]

    batch = torch.cat(batch, 0)
    batch = batch.view(3,in_dim, -1 )
    batch = batch.permute(1,0,2)
    return batch

def find_neighbors(idx, adj,  thres = 250,order = 1):
    #find all neighbors of given nodes(including itself)
    idx = np.array(torch.flatten(idx).cpu()).astype(int)
    neighbors = idx
    for _ in range(order):
        trun_adj = adj[neighbors, :]
        _, neighbors = np.where(trun_adj==1)
        neighbors = np.array(list(set(neighbors))).astype(int)
    #print("neighbors shape before:",neighbors.shape)
    if neighbors.shape[0]>thres:
        neighbors = np.random.choice(neighbors, thres)
        #print("neighbors shape after:", neighbors.shape)

    return np.array(list(set(idx).union(set(neighbors))))

def fakeAdj(adj = None, num_edge = None):
    # generate a random graph
    n = adj.shape[0]
    return nx.adjacency_matrix(nx.gnm_random_graph(n, num_edge)) + np.eye(n)

def neiAdj(adj = None):
    n = adj.shape[0]
    # only paper neighbor
    #adj = np.zeros(adj.shape) + np.eye(adj.shape[0])
    adj[0,1] = 1
    adj[n-1,n-2] = 1
    for i in range(2, n-2):
        adj[i,i+1] = 1
        adj[i,i-1] = 1
        adj[i,i+2] = 1
        adj[i,i-2] = 1
    return adj

def iter_rule_update(BM, OM, n_iter = 3):
    '''
    iteratively find the ground truth by applying rules
    rules: 
    if Bij Ojk, then Bik
    if Oij Bjk, then Bik
    if Bij Bjk, then Bik
    if Oij Ojk, then Oik
    if Oij, then Oji
    '''
    # first complete OM
    OM = OM + OM.transpose()
    OM = OM + np.matmul(OM, OM)
    # iteratively update BM
    for _ in range(n_iter):
        BM = BM + np.matmul(BM, OM)
        BM = BM + np.matmul(OM, BM)
        BM = BM + np.matmul(BM, BM)
    # normalize
    BM[np.where(BM>0)] = 1
    OM[np.where(OM>0)] = 1
    return BM, OM

def rule_tensor(A, B):
    '''
    Cijk = Aij * Bjk
    '''
    n = A.shape[0]
    A = A.reshape(n,n,1)
    B = B.reshape(1,n,n)
    C = A*B
    
    return C

def build_super_dataset(rel = None, batch = None):
    emb =[]
    labels = []
    for [i,j,r] in rel:
        emb.append(torch.tensor([i,j]))
        labels.append(r)
    
    all_embs = torch.stack(emb).cuda()
    all_labels = torch.tensor(labels,dtype=torch.long).cuda()   
    #logger.info("relation dataset node embedding size: %s" % str(all_inputs.size()))
    #print(len(batch))
    #print(all_embs.size(),all_labels.size(), batch[0:all_labels.size()[0],:].size())
    #print(all_embs, all_labels)
    all_ids, all_ats, all_tos = batch 
    relation_dataset = TensorDataset(all_embs, all_labels, torch.tensor(all_ids).cuda(), torch.tensor(all_ats).cuda(), torch.tensor(all_tos).cuda())

    return relation_dataset

    


def build_PSL_dataset(adj = None, rel = None, random_sampling = False, n_rule = 100):
    # convert origin matrix to before matrix and after matrix
    # augment data from transivity rules

    n = adj.shape[0]
    BM = np.zeros((n,n))
    OM = np.zeros((n,n))
    for [j,k,r] in rel:
        if r==0:
            OM[j,k]=1
        if r==1:
            BM[j,k]=1
        if r==2:
            BM[k,j]=1
    #print("Before Before:", 2*len(np.where(BM>0)[0]))
    #print("Before Overlap:", len(np.where(OM>0)[0]))
    # BM, OM = iter_rule_update(BM, OM, n_iter = 3)
    dense_adj = BM+OM+BM.transpose()
    dense_adj[np.where(dense_adj>0)] = 1
    #print("Updated Before:", 2*len(np.where(BM>0)[0]))
    #print("UPdated Overlap:", len(np.where(OM>0)[0]))
    #B_link = len(np.where(BM>0)[0])
    #O_link = len(np.where(OM>0)[0])
    #print("connectivity: ", (B_link+O_link)/n/(n-1))

    # construct all rules tensor
    BBB = rule_tensor(BM, BM)
    BOB = rule_tensor(BM, OM)
    OBB = rule_tensor(OM, BM)
    OOO = rule_tensor(OM, OM)
    All_rules = BBB+BOB+OBB+OOO
    all_x, all_y, all_z = np.where(All_rules>0)
    #print("rules in origin data:", all_x.shape)
    emb =[]
    labels = []

    if random_sampling:
        tmp_emb, tmp_labels = build_rules(rule = 'BBB', rule_tensor = BBB, n_rule = n_rule)
        emb.extend(tmp_emb)
        labels.extend(tmp_labels)
        tmp_emb, tmp_labels = build_rules(rule = 'BOB', rule_tensor = BOB, n_rule = n_rule)
        emb.extend(tmp_emb)
        labels.extend(tmp_labels)
        tmp_emb, tmp_labels = build_rules(rule = 'OBB', rule_tensor = OBB, n_rule = n_rule)
        emb.extend(tmp_emb)
        labels.extend(tmp_labels)
        tmp_emb, tmp_labels = build_rules(rule = 'OOO', rule_tensor = OOO, n_rule = n_rule)
        emb.extend(tmp_emb)
        labels.extend(tmp_labels)
    else:
        for [j,k,r] in rel:
            # for no rules found
            if np.where(all_x==j)[0].shape[0]==0 or np.where(all_y==k)[0].shape[0]==0 or len(set(np.where(all_x==j)[0]).intersection(set(np.where(all_y==k)[0])))==0:
                #emb.append(torch.tensor([j,k]))
                emb.extend([torch.tensor([j,k]),torch.tensor([j,k]),torch.tensor([j,k])])
                emb.extend([torch.tensor([k,j]),torch.tensor([k,j]),torch.tensor([k,j])])
                if r ==0:
                    #labels.append(r)
                    labels.extend([r,r,r])
                    labels.extend([r,r,r])
                if r ==1:
                    #labels.append(r)
                    labels.extend([r,r,r])
                    labels.extend([2,2,2])
                if r ==2:
                    #labels.append(r)
                    labels.extend([r,r,r])
                    labels.extend([1,1,1])
                continue
            if r==2:
                j,k = k,j
            # sample from rules
            rule_exist = set(np.where(all_x==j)[0]).intersection(set(np.where(all_y==k)[0]))
            common_neigh = all_z[random.sample(rule_exist, 1)[0]]
            # build PSL dataset, and their sysmetric version
            '''
            rules encoding:
            BBB:0, AAA:1, BOB:2, AOA:3, OBB:4, OAA:5, OOO:6, None:7
            '''
            if BBB[j,k,common_neigh]>0:
                #emb.append(torch.tensor([j,k]))
                emb.extend([torch.tensor([j,k]),torch.tensor([k,common_neigh]),torch.tensor([j,common_neigh])])
                emb.extend([torch.tensor([k,j]),torch.tensor([common_neigh,k]),torch.tensor([common_neigh,j])])
                #labels.append(1)
                labels.extend([1,1,1])
                labels.extend([2,2,2])
            if BOB[j,k,common_neigh]>0:
                #emb.append(torch.tensor([j,k]))
                emb.extend([torch.tensor([j,k]),torch.tensor([k,common_neigh]),torch.tensor([j,common_neigh])])
                emb.extend([torch.tensor([k,j]),torch.tensor([common_neigh,k]),torch.tensor([common_neigh,j])])
                #labels.append(1)
                labels.extend([1,0,1])
                labels.extend([2,0,2])
            if OBB[j,k,common_neigh]>0:
                #emb.append(torch.tensor([j,k]))
                emb.extend([torch.tensor([j,k]),torch.tensor([k,common_neigh]),torch.tensor([j,common_neigh])])
                emb.extend([torch.tensor([k,j]),torch.tensor([common_neigh,k]),torch.tensor([common_neigh,j])])
                #labels.append(0)
                labels.extend([0,1,1])
                labels.extend([0,2,2])
            if OOO[j,k,common_neigh]>0:
                #emb.append(torch.tensor([j,k]))
                emb.extend([torch.tensor([j,k]),torch.tensor([k,common_neigh]),torch.tensor([j,common_neigh])])
                emb.extend([torch.tensor([k,j]),torch.tensor([common_neigh,k]),torch.tensor([common_neigh,j])])
                #labels.append(0)
                labels.extend([0,0,0])
                labels.extend([0,0,0])

    all_embs = torch.stack(emb).cuda()
    all_labels = torch.tensor(labels,dtype=torch.long).cuda()   
    #logger.info("relation dataset node embedding size: %s" % str(all_inputs.size()))
    relation_dataset = TensorDataset(all_embs, all_labels)

    return relation_dataset, dense_adj


def build_rules(rule = None, rule_tensor = None, n_rule = None):
    all_x, all_y, all_z = np.where(rule_tensor>0)
    n = all_x.shape[0]
    if n==0:
        return [],[]
    rules = [random.randint(0,n-1) for _ in range(n_rule)]
    all_x, all_y, all_z = all_x[rules], all_y[rules], all_z[rules]
    emb = []
    labels = []
    #TODO: think of vector way
    for i in range(n_rule):
        x,y,z = all_x[i],all_y[i], all_z[i]
        emb.extend([torch.tensor([x,y]),torch.tensor([y,z]),torch.tensor([x,z])])
        emb.extend([torch.tensor([y,x]),torch.tensor([z,y]),torch.tensor([z,x])])

    if rule == 'BBB':
        for i in range(n_rule):
            labels.extend([1,1,1])
            labels.extend([2,2,2])
    if rule == 'BOB':
        for i in range(n_rule):
            labels.extend([1,0,1])
            labels.extend([2,0,2])
    if rule == 'OBB':
        for i in range(n_rule):
            labels.extend([0,1,1])
            labels.extend([0,2,2])            
    if rule == 'OOO':
        for i in range(n_rule):
            labels.extend([0,0,0])
            labels.extend([0,0,0])
    
    return emb, labels


webhook_url = "https://hooks.slack.com/services/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"
@slack_sender(webhook_url=webhook_url, channel="coding-notification")
def main():
    parser = argparse.ArgumentParser()

    ## Required parameters
    parser.add_argument("--data_dir", default=None, type=str, required=True,
                        help="The input data dir. Should contain the .tsv files (or other data files) for the task.")
    parser.add_argument("--model_type", default=None, type=str, required=True,
                        help="Model type selected in the list: " + ", ".join(MODEL_CLASSES.keys()))
    parser.add_argument("--model_name_or_path", default=None, type=str, required=True,
                        help="Path to pre-trained model or shortcut name selected in the list: " + ", ".join(ALL_MODELS))
    parser.add_argument("--task_name", default=None, type=str, required=True,
                        help="The name of the task to train selected in the list: " + ", ".join(processors.keys()))
    parser.add_argument("--output_dir", default=None, type=str, required=True,
                        help="The output directory where the model predictions and checkpoints will be written.")

    ## Other parameters
    parser.add_argument("--config_name", default="", type=str,
                        help="Pretrained config name or path if not the same as model_name")
    parser.add_argument("--tokenizer_name", default="", type=str,
                        help="Pretrained tokenizer name or path if not the same as model_name")
    parser.add_argument("--cache_dir", default="", type=str,
                        help="Where do you want to store the pre-trained models downloaded from s3")
    parser.add_argument("--max_seq_length", default=128, type=int,
                        help="The maximum total input sequence length after tokenization. Sequences longer "
                             "than this will be truncated, sequences shorter will be padded.")
    parser.add_argument("--do_train", action='store_true',
                        help="Whether to run training.")
    parser.add_argument("--do_eval", action='store_true',
                        help="Whether to run eval on the dev set.")
    parser.add_argument("--evaluate_during_training", action='store_true',
                        help="Rul evaluation during training at each logging step.")
    parser.add_argument("--do_lower_case", action='store_true',
                        help="Set this flag if you are using an uncased model.")

    parser.add_argument("--per_gpu_train_batch_size", default=8, type=int,
                        help="Batch size per GPU/CPU for training.")
    parser.add_argument("--per_gpu_eval_batch_size", default=8, type=int,
                        help="Batch size per GPU/CPU for evaluation.")
    parser.add_argument('--gradient_accumulation_steps', type=int, default=1,
                        help="Number of updates steps to accumulate before performing a backward/update pass.")     
    parser.add_argument("--learning_rate", default=5e-5, type=float,
                        help="The initial learning rate for Adam.")
    parser.add_argument("--weight_decay", default=0.0, type=float,
                        help="Weight deay if we apply some.")
    parser.add_argument("--adam_epsilon", default=1e-8, type=float,
                        help="Epsilon for Adam optimizer.")
    parser.add_argument("--max_grad_norm", default=1.0, type=float,
                        help="Max gradient norm.")
    parser.add_argument("--num_train_epochs", default=3.0, type=float,
                        help="Total number of training epochs to perform.")
    parser.add_argument("--max_steps", default=-1, type=int,
                        help="If > 0: set total number of training steps to perform. Override num_train_epochs.")
    parser.add_argument("--warmup_steps", default=0, type=int,
                        help="Linear warmup over warmup_steps.")

    parser.add_argument('--logging_steps', type=int, default=500,
                        help="Log every X updates steps.")
    parser.add_argument('--save_steps', type=int, default=500,
                        help="Save checkpoint every X updates steps.")
    parser.add_argument("--eval_all_checkpoints", action='store_true',
                        help="Evaluate all checkpoints starting with the same prefix as model_name ending and ending with step number")
    parser.add_argument("--no_cuda", action='store_true',
                        help="Avoid using CUDA when available")
    parser.add_argument('--overwrite_output_dir', action='store_true',
                        help="Overwrite the content of the output directory")
    parser.add_argument('--overwrite_cache', action='store_true',
                        help="Overwrite the cached training and evaluation sets")
    parser.add_argument('--seed', type=int, default=42,
                        help="random seed for initialization")

    parser.add_argument('--fp16', action='store_true',
                        help="Whether to use 16-bit (mixed) precision (through NVIDIA apex) instead of 32-bit")
    parser.add_argument('--fp16_opt_level', type=str, default='O1',
                        help="For fp16: Apex AMP optimization level selected in ['O0', 'O1', 'O2', and 'O3']."
                             "See details at https://nvidia.github.io/apex/amp.html")
    parser.add_argument("--local_rank", type=int, default=-1,
                        help="For distributed training: local_rank")
    parser.add_argument('--server_ip', type=str, default='', help="For distant debugging.")
    parser.add_argument('--server_port', type=str, default='', help="For distant debugging.")
    parser.add_argument('--n_layer', type=int, default='', help="number of layer updated in bert")
    args = parser.parse_args()

    if os.path.exists(args.output_dir) and os.listdir(args.output_dir) and args.do_train and not args.overwrite_output_dir:
        raise ValueError("Output directory ({}) already exists and is not empty. Use --overwrite_output_dir to overcome.".format(args.output_dir))

    # Setup distant debugging if needed
    if args.server_ip and args.server_port:
        # Distant debugging - see https://code.visualstudio.com/docs/python/debugging#_attach-to-a-local-script
        import ptvsd
        print("Waiting for debugger attach")
        ptvsd.enable_attach(address=(args.server_ip, args.server_port), redirect_output=True)
        ptvsd.wait_for_attach()

    # Setup CUDA, GPU & distributed training
    if args.local_rank == -1 or args.no_cuda:
        device = torch.device("cuda" if torch.cuda.is_available() and not args.no_cuda else "cpu")
        args.n_gpu = torch.cuda.device_count()
    else:  # Initializes the distributed backend which will take care of sychronizing nodes/GPUs
        torch.cuda.set_device(args.local_rank)
        device = torch.device("cuda", args.local_rank)
        torch.distributed.init_process_group(backend='nccl')
        args.n_gpu = 1
    args.device = device

    # Setup logging
    logging.basicConfig(format = '%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                        datefmt = '%m/%d/%Y %H:%M:%S',
                        level = logging.INFO if args.local_rank in [-1, 0] else logging.WARN)
    logger.warning("Process rank: %s, device: %s, n_gpu: %s, distributed training: %s, 16-bits training: %s",
                    args.local_rank, device, args.n_gpu, bool(args.local_rank != -1), args.fp16)

    # Set seed
    set_seed(args)

    # Prepare GLUE task
    args.task_name = args.task_name.lower()
    if args.task_name not in processors:
        raise ValueError("Task not found: %s" % (args.task_name))
    processor = processors[args.task_name]()
    args.output_mode = output_modes[args.task_name]
    label_list = processor.get_labels()
    num_labels = len(label_list)
    logger.info("num_labels: %s" % str(num_labels))

    # Load pretrained model and tokenizer
    if args.local_rank not in [-1, 0]:
        torch.distributed.barrier()  # Make sure only the first process in distributed training will download model & vocab

    args.model_type = args.model_type.lower()
    config_class, model_class, tokenizer_class, model_emb = GRAPH_CLASSES[args.model_type]
    config = config_class.from_pretrained(args.config_name if args.config_name else args.model_name_or_path,
                                          num_labels=num_labels,
                                          finetuning_task=args.task_name,
                                          cache_dir=args.cache_dir if args.cache_dir else None)
    print(type(config))

    tokenizer = tokenizer_class.from_pretrained(args.tokenizer_name if args.tokenizer_name else args.model_name_or_path,
                                                do_lower_case=args.do_lower_case,
                                                cache_dir=args.cache_dir if args.cache_dir else None)

    model = model_emb.from_pretrained(args.model_name_or_path,
                                        from_tf=bool('.ckpt' in args.model_name_or_path),
                                        config=config,
                                        cache_dir=args.cache_dir if args.cache_dir else None)

    # classifier = model_class.from_pretrained(args.model_name_or_path,
    #                                     from_tf=bool('.ckpt' in args.model_name_or_path),
    #                                     #config=config,
    #                                     cache_dir=args.cache_dir if args.cache_dir else None)
    classifier = model_class(config = config)
    #conv_graph = ConvGraph(config = config)

    # conv_graph = ConvGraph.from_pretrained(args.model_name_or_path,
    #                                     from_tf=bool('.ckpt' in args.model_name_or_path),
    #                                     #config=config,
    #                                     cache_dir=args.cache_dir if args.cache_dir else None)


    if args.local_rank == 0:
        torch.distributed.barrier()  # Make sure only the first process in distributed training will download model & vocab

    model.to(args.device)
    #conv_graph.to(args.device)
    classifier.to(args.device)

    logger.info("Training/evaluation parameters %s", args)

    # Training
    if args.do_train and not args.do_eval:
        train_dataset = load_and_cache_examples(args, args.task_name, tokenizer, evaluate=False)
        global_step, tr_loss = train(args, train_dataset, model, classifier,tokenizer)# conv_graph, 
        logger.info(" global_step = %s, average loss = %s", global_step, tr_loss)

    if args.do_eval and args.do_train:
        eval_dataset = load_and_cache_examples(args, args.task_name, tokenizer, evaluate=True)
        epoch = args.num_train_epochs
        for i in range(int(epoch)):
            print("This is the %dth epoch"%(i+1))
            train_dataset = load_and_cache_examples(args, args.task_name, tokenizer, evaluate=False)# conv_graph, 
            global_step, tr_loss = train(args, train_dataset, model, classifier,tokenizer, eval_dataset=eval_dataset)
            logger.info(" global_step = %s, average loss = %s", global_step, tr_loss)


    # # Saving best-practices: if you use defaults names for the model, you can reload it using from_pretrained()
    # if args.do_train and (args.local_rank == -1 or torch.distributed.get_rank() == 0):
    #     # Create output directory if needed
    #     if not os.path.exists(args.output_dir) and args.local_rank in [-1, 0]:
    #         os.makedirs(args.output_dir)

    #     logger.info("Saving model checkpoint to %s", args.output_dir)
    #     # Save a trained model, configuration and tokenizer using `save_pretrained()`.
    #     # They can then be reloaded using `from_pretrained()`
    #     model_to_save = model.module if hasattr(model, 'module') else model  # Take care of distributed/parallel training
    #     model_to_save.save_pretrained(args.output_dir)
    #     tokenizer.save_pretrained(args.output_dir)
    #     torch.save(classifier.state_dict(), args.output_dir)
    #     torch.save(conv_graph.state_dict(), args.output_dir)

    #     # Good practice: save your training arguments together with the trained model
    #     torch.save(args, os.path.join(args.output_dir, 'training_args.bin'))

    #     # Load a trained model and vocabulary that you have fine-tuned
    #     model = model_emb.from_pretrained(args.output_dir)
    #     classifier = model_class(config = config)
    #     conv_graph = ConvGraph(config = config)
    #     classifier.load_state_dict(torch.load(args.output_dir))
    #     conv_graph.load_state_dict(torch.load(args.output_dir))
    #     tokenizer = tokenizer_class.from_pretrained(args.output_dir)
    #     model.to(args.device)
    #     conv_graph.to(args.device)
    #     classifier.to(args.device)

    # # Evaluation
    # results = {}
    # if args.do_eval and args.local_rank in [-1, 0]:
    #     tokenizer = tokenizer_class.from_pretrained(args.output_dir, do_lower_case=args.do_lower_case)
    #     checkpoints = [args.output_dir]
    #     if args.eval_all_checkpoints:
    #         checkpoints = list(os.path.dirname(c) for c in sorted(glob.glob(args.output_dir + '/**/' + WEIGHTS_NAME, recursive=True)))
    #         logging.getLogger("transformers.modeling_utils").setLevel(logging.WARN)  # Reduce logging
    #     logger.info("Evaluate the following checkpoints: %s", checkpoints)
    #     for checkpoint in checkpoints:
    #         global_step = checkpoint.split('-')[-1] if len(checkpoints) > 1 else ""
    #         prefix = checkpoint.split('/')[-1] if checkpoint.find('checkpoint') != -1 else ""
            
    #         model = model_class.from_pretrained(checkpoint)
    #         model.to(args.device)
    #         result = evaluate(args, model, tokenizer, prefix=prefix)
    #         result = dict((k + '_{}'.format(global_step), v) for k, v in result.items())
    #         results.update(result)

    # return results


if __name__ == "__main__":
    main()