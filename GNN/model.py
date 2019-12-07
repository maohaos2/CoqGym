import torch
import torch.nn as nn
import torch.functional as F
import dgl

class MLP(nn.Module):
    """
    used for MLP_v and MLP_e in the main model.
    two hidden layers of sizes 256 and 128 with ReLU activations.
    """
    def __init__(self, input_size, output_size, dropout_rate=0.5):
        super(MLP, self).__init__()
        self.fc1 = nn.Linear(input_size, 256)
        self.relu1 = nn.ReLU()
        self.drop1 = nn.Dropout(dropout_rate)
        self.fc2 = nn.Linear(256, 128)
        self.relu2 = nn.ReLU()
        self.drop2 = nn.Dropout(dropout_rate)
        self.fc3 = nn.Linear(128, output_size)

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu1(out)
        out = self.drop1(out)
        out = self.fc2(out)
        out = self.relu2(out)
        out = self.drop2(out)
        out = self.fc3(out)
        return out

class GNN(nn.Module):
    """
    the GNN model.
    deals only with connected graphs.
    T - total number of hops.
    """
    def __init__(self, T):
        self.T = T
        self.t = None # current time step.
        self.MLP_v = MLP(128, 128)
        self.MLP_e = MLP(1, 128) # why?
        self.MLP_edge_1 = nn.ModuleList([MLP(128*3, 128)]) # computes message from parent nodes.
        self.MLP_edge_0 = nn.ModuleList([MLP(128*3, 128)]) # computes message from child nodes.
        self.MLP_aggr = MLP(128*3, 128)

    def message_1(self, e):
        """
        computes the message along an edge whose label is 1.
        e - an edge.
        t - current time step.
        """
        t = self.t
        u, v = e.src, e.dst
        message = self.MLP_edge_1[t].forward(
            torch.cat(e.src['h_v'], e.dst['h_v'], e['h_e']), 0
        )
        return {'m_1': message}

    def message_c(self, e):
        """
        computes the message along an edge whose label is 0.
        e - an edge.
        t - current time step.
        """
        t = self.t
        u, v = e.src, e.dst
        message = self.MLP_edge_0[t].forward(
            torch.cat(e.src['h_v'], e.dst['h_v'], e['h_e']), 0
        )
        return {'m_0': message}

    def update(self, v):
        """
        the update function.
        v - a node.
        t - current time step.
        """
        t = self.t
        avg_m_1 = torch.mean(v.mailbox['m_1'], dim=1)
        avg_m_0 = torch.mean(v.mailbox['m_0'], dim=1)
        h_old = v['h_v']
        h_new = self.MLP_aggr[t].forward(
            torch.cat((h_old, avg_m_1, avg_m_0))
        )
        h_new = h_new + h_old
        h_new = F.relu(h_new)
        return {'h_v': h_new}

    def forward(self, e_1, e_0, g):
        """
        g - a directed graph with boolean edge labels.
        e_1 - array of edges labeled as 1.
        e_0 - array of edges labeled as 0.
        """
        for v in g.nodes():
            # initialize node embeddings from (the embedding of) node labels.
            x_v = g.nodes[v]['x_v']
            g.nodes[v]['h_v'] = self.MLP_v.forward(x_v)
        for e in g.edges():
            # initialize edge embeddings from edge labels.
            l_e = g.nodes[e]['l_e']
            g.edges[e]['h_e'] = self.MLP_e.forward(l_e) # abusing nn.

        # message passing.
        for t in range(self.T):
            self.t = t
            # compute the messages
            g.send(e_1, self.message_1)
            g.send(e_0, self.message_0)
            # update according to message.
            g.recv(g.nodes, self.update)

        # readout
        # diverges from original paper
        return g


# Note
# structure of g:
#     - for each node v:
#         - x_v: embedding of its 'token'
#         - h_v: node embeddings
#     - for each edge e:
#         - l_e: 0 or 1.
#         - h_e: embedding derived from 0 or 1. The paper derived this by passing this trough a MLP. Why not just make trainable embeddings for 0 and 1? Wired.
# TODO: compatibality with coqgym