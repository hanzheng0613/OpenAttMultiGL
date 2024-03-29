'''
    Code for IJCAI 2021 paper "Graph Filter-based Multi-view Attributed Graph Clustering
    
    https://github.com/sckangz/MvAGC/tree/main
    
'''
from sklearn.metrics import f1_score
from sklearn.metrics import roc_auc_score
from sklearn.metrics import average_precision_score
from sklearn.metrics import normalized_mutual_info_score
from sklearn.metrics import pairwise

from sklearn import metrics
from munkres import Munkres, print_matrix
import numpy as np
import argparse
from OpenAttMultiGL.model.mGCN.mGCN_node import*
from OpenAttMultiGL.utils.process import * 
from OpenAttMultiGL.layers.hdmi.gcn import GCN
import torch.nn as nn
import torch.optim as optim
import torch
from OpenAttMultiGL.utils.dataset import dataset
from OpenAttMultiGL.utils.process import split_node_data
from sklearn.metrics import roc_auc_score

def combine_att(h_list):
    att_act1 = nn.Tanh()
    att_act2 = nn.Softmax(dim=-1)
    h_combine_list = []
    for i, h in enumerate(h_list):
        h = w_list[i](h)
        h = y_list[i](h)
        h_combine_list.append(h)
    score = torch.cat(h_combine_list, -1)
    score = att_act1(score)
    score = att_act2(score)
    score = torch.unsqueeze(score, -1)
    h = torch.stack(h_list, dim=1)
    h = score * h
    h = torch.sum(h, dim=1)
    return h

def embed(seq, adj_list, sparse,n_networks,ft_size):
    global w_list
    global y_list

    hid_units = 128
    gcn_list = nn.ModuleList([GCN(ft_size, hid_units) for _ in range(n_networks)])
    w_list = nn.ModuleList([nn.Linear(hid_units, hid_units, bias=False) for _ in range(n_networks)])
    y_list = nn.ModuleList([nn.Linear(hid_units, 1) for _ in range(n_networks)])
    h_1_list = []
    for i, adj in enumerate(adj_list):
        h_1 = torch.squeeze(gcn_list[i](seq, adj, sparse))
        h_1_list.append(h_1)
    h = combine_att(h_1_list)
    return h.detach()

def run_similarity_search(test_embs, test_lbls):
    numRows = test_embs.shape[0]
    sim = []
    cos_sim_array = pairwise.cosine_similarity(test_embs) - np.eye(numRows)
    st = []
    for N in [5, 10, 20, 50, 100]:
        indices = np.argsort(cos_sim_array, axis=1)[:, -N:]
        tmp = np.tile(test_lbls, (numRows, 1))
        selected_label = tmp[np.repeat(np.arange(numRows), N), indices.ravel()].reshape(numRows, N)
        original_label = np.repeat(test_lbls, N).reshape(numRows,N)
        st.append(str(np.round(np.mean(np.sum((selected_label == original_label), 1) / N), 4)))
    for i in st:
        sim.append(float(i))
    st = ','.join(st)
    
    sim_mean = np.mean(sim)
    #print("\t[Similarity] [5,10,20,50,100] : [{}]".format(st))
    return sim

class linkpred_metrics():
    def __init__(self, edges_pos, edges_neg):
        self.edges_pos = edges_pos
        self.edges_neg = edges_neg

    def get_roc_score(self, emb, feas):
        # if emb is None:
        #     feed_dict.update({placeholders['dropout']: 0})
        #     emb = sess.run(model.z_mean, feed_dict=feed_dict)

        def sigmoid(x):
            return 1 / (1 + np.exp(-x))

        # Predict on test set of edges
        adj_rec = np.dot(emb, emb.T)
        preds = []
        pos = []
        for e in self.edges_pos:
            preds.append(sigmoid(adj_rec[e[0], e[1]]))
            pos.append(feas['adj_orig'][e[0], e[1]])

        preds_neg = []
        neg = []
        for e in self.edges_neg:
            preds_neg.append(sigmoid(adj_rec[e[0], e[1]]))
            neg.append(feas['adj_orig'][e[0], e[1]])

        preds_all = np.hstack([preds, preds_neg])
        labels_all = np.hstack([np.ones(len(preds)), np.zeros(len(preds))])
        roc_score = roc_auc_score(labels_all, preds_all)
        ap_score = average_precision_score(labels_all, preds_all)

        return roc_score, ap_score, emb


class clustering_metrics():
    def __init__(self, true_label, predict_label):
        self.true_label = true_label
        self.pred_label = predict_label
        
    
                

    def clusteringAcc(self):
        # best mapping between true_label and predict label
        l1 = list(set(self.true_label))
        numclass1 = len(l1)

        l2 = list(set(self.pred_label))
        numclass2 = len(l2)
        if numclass1 != numclass2:
            print('Class Not equal, Error!!!!')
            return 0

        cost = np.zeros((numclass1, numclass2), dtype=int)
        for i, c1 in enumerate(l1):
            mps = [i1 for i1, e1 in enumerate(self.true_label) if e1 == c1]
            for j, c2 in enumerate(l2):
                mps_d = [i1 for i1 in mps if self.pred_label[i1] == c2]

                cost[i][j] = len(mps_d)

        # match two clustering results by Munkres algorithm
        m = Munkres()
        cost = cost.__neg__().tolist()

        indexes = m.compute(cost)

        # get the match results
        new_predict = np.zeros(len(self.pred_label))
        for i, c in enumerate(l1):
            # correponding label in l2:
            c2 = l2[indexes[i][1]]

            # ai is the index with label==c2 in the pred_label list
            ai = [ind for ind, elm in enumerate(self.pred_label) if elm == c2]
            new_predict[ai] = c

        acc = metrics.accuracy_score(self.true_label, new_predict)
        f1_macro = metrics.f1_score(
            self.true_label, new_predict, average='macro')
        
        f1_micro = metrics.f1_score(
            self.true_label, new_predict, average='micro')
        
        
        c = dataset('amazon')
        sparse = True
        labels = torch.FloatTensor(c.gcn_labels)
        idx_train = torch.LongTensor(c.train_id)
        idx_val = torch.LongTensor(c.valid_id)
        idx_test = torch.LongTensor(c.test_id)
        
        preprocessed_features = preprocess_features(c.features)
        ft_size = preprocessed_features[0].shape[1] 
        hid_units = 128
        n_networks = len(c.adj_list)
        features = torch.FloatTensor(preprocessed_features)
        gcn_adj_list = [normalize_adj(adj) for adj in c.gcn_adj_list]
        adj_list = [sparse_mx_to_torch_sparse_tensor(adj) for adj in gcn_adj_list]
        embeds = embed(features, adj_list, sparse,n_networks,ft_size)
        test_embs = embeds[idx_test]

        
        test_lbls = torch.argmax(labels[idx_test], dim=1)
        
        
        test_embs = np.array(test_embs)
        test_lbls = np.array(test_lbls)
        
        
        sim = run_similarity_search(test_embs, test_lbls)
        sim = sim[0]
        return f1_macro,f1_micro, sim
    
    

    def evaluationClusterModelFromLabel(self,m,a,k):
        nmi = metrics.normalized_mutual_info_score(
            self.true_label, self.pred_label)
        adjscore = metrics.adjusted_rand_score(
            self.true_label, self.pred_label)
        f1_macro, f1_micro,sim = self.clusteringAcc()

        print('f1_macro=%f,f1_micro=%f, NMI=%f, SIM=%f' % (f1_macro,f1_micro,nmi,sim))

        fh = open('recoderimdkA3.txt', 'a')

        fh.write('m=%f,a=%f,k=%f, f1_macro=%f, f1_micro=%f,  NMI=%f, SIM=%f' % (m,a,k,
            f1_macro, f1_micro, nmi, sim))
        fh.write('\r\n')
        fh.flush()
        fh.close()

        return f1_micro, f1_macro, nmi,sim
    
    
