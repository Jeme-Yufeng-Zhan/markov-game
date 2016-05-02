# coding=utf-8

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

import random
import sys
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from numba import jit
from functools import partial

import numpy as np

if sys.version_info >= (3, 0):
    from pulp import *
else:
    from pulp import *
    try:
        from gurobipy import *
    except:
        pass
import pickle

import strategy

__author__ = 'Aijun Bai'


@jit(nopython=True)
def jit_q_update(Q1, Q2, a, r, alpha, gamma):
    Q1[a] += alpha * (r + gamma * np.max(Q2) - Q1[a])

@jit(nopython=True)
def jit_minimax_dot(pi, Q, o):
    return np.dot(pi, Q[:, o])

@jit(nopython=True)
def jit_minimax_update(Q, v, a, o, r, alpha, gamma):
    Q[a, o] += alpha * (r + gamma * v - Q[a, o])

class Agent(object):
    __metaclass__ = ABCMeta

    def __init__(self, no, game, name, train=True):
        self.no = no  # player number
        self.name = name
        self.game = game
        self.train = train
        self.numactions = game.numactions(self.no)
        self.opp_numactions = game.numactions(1 - self.no)

    @abstractmethod
    def done(self):
        print('agent {}_{} done...'.format(self.name, self.no))

    @abstractmethod
    def act(self, s):
        pass

    @abstractmethod
    def update(self, s, a, o, r, ns):
        pass

    def pickle_name(self):
        return '{}_{}.pickle'.format(self.name, self.no)


class StationaryAgent(Agent):
    def __init__(self, no, game, pi=None):
        super().__init__(no, game, 'stationary', train=False)
        self.strategy = strategy.Strategy(self.numactions, pi=pi)

    def done(self):
        super().done()

    def act(self, s):
        return self.strategy.sample()

    def update(self, s, a, o, r, ns):
        pass

class RandomAgent(StationaryAgent):
    def __init__(self, no, game):
        n = game.numactions(no)
        super().__init__(no, game, [1.0 / n] * n)


class QAgent(Agent):
    def __init__(self, no, game, train=True, episilon=0.2, alpha=1.0):
        super().__init__(no, game, 'q', train=train)

        self.episilon = episilon
        self.alpha = alpha

        if self.train:
            self.Q = defaultdict(partial(np.random.rand, self.numactions))
        else:
            with open(self.pickle_name(), 'rb') as f:
                self.Q = pickle.load(f)

    def done(self):
        super().done()
        if self.train:
            with open(self.pickle_name(), 'wb') as f:
                pickle.dump(self.Q, f)

    def act(self, s):
        if self.train and random.random() < self.episilon:
            return random.randint(0, self.numactions - 1)
        else:
            return np.argmax(self.Q[s])

    def update(self, s, a, o, r, ns):
        jit_q_update(self.Q[s], self.Q[ns], a, r, self.alpha, self.game.gamma)
        self.alpha *= 0.9999954


class MinimaxQAgent(Agent):
    def __init__(self, no, game, train=True, episilon=0.2, alpha=1.0):
        super().__init__(no, game, 'minimax', train=train)

        self.episilon = episilon
        self.alpha = alpha

        if self.train:
            self.Q = defaultdict(partial(np.random.rand, self.numactions, self.opp_numactions))
            self.strategy = defaultdict(partial(strategy.Strategy, self.numactions))
        else:
            with open(self.pickle_name(), 'rb') as f:
                self.Q, self.strategy = pickle.load(f)

    def done(self):
        super().done()

        if self.train:
            with open(self.pickle_name(), 'wb') as f:
                pickle.dump((self.Q, self.strategy), f)

    def val(self, s):
        return min(jit_minimax_dot(self.strategy[s].pi, self.Q[s], o)
                   for o in range(self.opp_numactions))

    def act(self, s):
        if self.train and random.random() < self.episilon:
            return random.randint(0, self.numactions - 1)
        else:
            return self.strategy[s].sample()

    def update_strategy(self, s, solver='gurobi'):
        if solver == 'gurobi':
            m = Model('LP')
            m.setParam('OutputFlag', 0)
            m.setParam('LogFile', '')
            m.setParam('LogToConsole', 0)
            v = m.addVar(name='v')
            pi = {}
            for a in range(self.numactions):
                pi[a] = m.addVar(lb=0.0, ub=1.0, name='pi_{}'.format(a))
            m.update()
            m.setObjective(v, sense=GRB.MAXIMIZE)
            for o in range(self.opp_numactions):
                m.addConstr(
                    quicksum(pi[a] * self.Q[s][a, o] for a in range(self.numactions)) >= v,
                    name='c_o{}'.format(o))
            m.addConstr(quicksum(pi[a] for a in range(self.numactions)) == 1, name='c_pi')
            m.optimize()
            self.strategy[s].update([pi[a].X for a in range(self.numactions)])
        elif solver == 'pulp':
            v = LpVariable('v')
            pi = LpVariable.dicts('pi', list(range(self.numactions)), 0, 1)
            prob = LpProblem('LP', LpMaximize)
            prob += v
            for o in range(self.opp_numactions):
                prob += lpSum(pi[a] * self.Q[s][a, o] for a in range(self.numactions)) >= v
            prob += lpSum(pi[a] for a in range(self.numactions)) == 1
            prob.solve(GLPK_CMD(msg=0))
            self.strategy[s].update([value(pi[a]) for a in range(self.numactions)])

        return None

    def update(self, s, a, o, r, ns):
        jit_minimax_update(self.Q[s], self.val(ns), a, o, r, self.alpha, self.game.gamma)
        self.alpha *= 0.9999954

        if sys.version_info >= (3, 0):
            self.update_strategy(s, solver='pulp')
        else:
            try:
                self.update_strategy(s, solver='gurobi')
            except:
                self.update_strategy(s, solver='pulp')


# class KappaAgent(Agent):
#     def __init__(self, no, game, N=25, episilon=0.1, alpha=0.01):
#         super().__init__(no, game, 'kapper')
#
#         self.episilon = episilon
#         self.alpha = alpha
#         self.numstrategies = N
#         self.particles = [particle.Particle(self) for _ in range(self.numstrategies)]
#         self.strategy = None
#         self.particles[-1].strategy.pi = np.full(self.particles[-1].strategy.pi.shape, 1.0 / self.numactions)
#
#     def act(self, exploration):
#         if exploration and random.random() < self.episilon:
#             self.strategy = random.choice(self.particles).strategy
#         else:
#             self.strategy = max(self.particles, key=(lambda x: x.val())).strategy
#         return self.strategy.sample()
#
#     def update(self, a, o, r):
#         k = r + self.game.gamma * max(x.val() for x in self.particles)
#
#         total_weight = 0.0
#         for p in self.particles:
#             w = p.strategy.pi[a] / self.strategy.pi[a]
#             p.K[o] += self.alpha * w * (k - p.K[o])
#             total_weight += p.strategy.pi[a]  # weight conditioned on observations?
#
#         distribution = [p.strategy.pi[a] / total_weight for p in self.particles]
#         outcomes = np.random.multinomial(self.numstrategies, distribution)
#         self.particles = [self.particles[i].clone() for i, c in enumerate(outcomes) for _ in range(c)]
#
#     def policy(self):
#         return max(self.particles, key=(lambda x: x.val())).strategy.pi
#
#     def report(self):
#         super().report()
#         eq = RandomAgent(self.no, self.game).strategy.pi
#         policies = ({'dist': np.linalg.norm(p.strategy.pi - eq), 'pi': p.strategy, 'val': p.val()} for i, p in
#                     enumerate(self.particles))
#         policies = sorted(policies, key=lambda x: x['dist'])
#         for i, p in enumerate(policies):
#             print('policy_{}:'.format(i), p)
