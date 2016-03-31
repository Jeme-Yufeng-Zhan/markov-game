# coding=utf-8

from __future__ import division
from __future__ import with_statement  # for python 2.5

import copy
import random

import numpy as np
import pulp as lp

import strategy

__author__ = 'Aijun Bai'


class Agent(object):
    def __init__(self, no, game, name):
        self.no = no  # player number
        self.name = name
        self.game = game
        self.numactions = game.numactions(self.no)
        self.opp_numactions = game.numactions(1 - self.no)

    def act(self, exploration):
        pass

    def update(self, a, o, r):
        pass

    def policy(self):
        pass

    def report(self):
        print 'name:', self.name
        print 'no:', self.no
        print 'strategy:', self.policy()


class StationaryAgent(Agent):
    def __init__(self, no, game, pi=None):
        super(StationaryAgent, self).__init__(no, game, 'stationary')
        self.strategy = strategy.Strategy(self.numactions, pi)

    def act(self, exploration):
        return self.strategy.sample()

    def policy(self):
        return self.strategy.pi()

class RandomAgent(StationaryAgent):
    def __init__(self, no, game):
        n = game.numactions(no)
        super(RandomAgent, self).__init__(no, game, [1.0 / n] * n)


class QAgent(Agent):
    def __init__(self, no, game, episilon=0.1, alpha=0.01):
        super(QAgent, self).__init__(no, game, 'q')

        self.episilon = episilon
        self.alpha = alpha

        self.Q = np.random.rand(self.numactions)

    def act(self, exploration):
        if exploration and random.random() < self.episilon:
            return random.randint(0, self.numactions - 1)
        else:
            return np.argmax(self.Q)

    def update(self, a, o, r):
        self.Q[a] += self.alpha * (r + self.game.gamma * max(self.Q[a] for a in range(self.numactions)) - self.Q[a])

    def policy(self):
        distri = [0] * self.numactions
        distri[np.argmax(self.Q)] = 1
        return distri

    def report(self):
        super(QAgent, self).report()
        print 'Q:', self.Q

class MinimaxQAgent(Agent):
    def __init__(self, no, game, episilon=0.1, alpha=0.01):
        super(MinimaxQAgent, self).__init__(no, game, 'minimax')

        self.episilon = episilon
        self.alpha = alpha

        self.Q = np.random.rand(self.numactions, self.opp_numactions)
        self.strategy = strategy.Strategy(self.numactions)

    def val(self, pi):
        return min(
            sum(p * q for p, q in zip(pi, (self.Q[a, o] for a in xrange(self.numactions))))
            for o in range(self.numactions))

    def act(self, exploration):
        if exploration and random.random() < self.episilon:
            return random.randint(0, self.numactions - 1)
        else:
            return self.strategy.sample()

    def update(self, a, o, r):
        self.Q[a, o] += self.alpha * (r + self.game.gamma * self.val(self.strategy.pi()) - self.Q[a, o])

        # update strategy
        v = lp.LpVariable('v')
        pi = lp.LpVariable.dicts('pi', range(self.numactions), 0, 1)
        prob = lp.LpProblem('maximizing', lp.LpMaximize)
        prob += v
        for o in range(self.opp_numactions):
            prob += lp.lpSum(pi[i] * self.Q[i, o] for i in range(self.numactions)) >= v
        prob += lp.lpSum(pi[i] for i in range(self.numactions)) == 1
        for i in range(self.numactions):
            prob += pi[i] >= 0
            prob += pi[i] <= 1
        # status = prob.solve(lp.COIN())
        status = prob.solve(lp.GUROBI(msg=False))
        if status == 1:
            self.strategy.update([lp.value(pi[i]) for i in range(self.numactions)])
        else:
            assert 0

    def policy(self):
        return self.strategy.pi()

    def report(self):
        super(MinimaxQAgent, self).report()
        eq = RandomAgent(self.no, self.game).strategy.pi()
        print 'dist:', np.linalg.norm(self.strategy.pi() - eq)
        print 'val:', self.val(self.strategy.pi())
        print 'Q:', self.Q

class KappaAgent(Agent):
    """
    there should be more updates for each policy, and more updates for the set of samples
    updates for particles -- posterior distributions
    importance sampling -- I have to work this out!
    a distribution over particles: the probability that the particle to be optimal -- thompson sampling idea
    like a bandit problem with thompson sampling
    update thompson sampling
    importance sampling idea => compact representation? propose new strategies?
    x-armed bandits idea
    particle filter idea
    """

    class Particle(object):
        def __init__(self, agent, weight, policy=None):
            self.agent = agent
            self.strategy = strategy.Strategy(self.agent.numactions, policy)
            self.weight = weight
            self.K = np.random.rand(self.agent.opp_numactions)

        def val(self):
            return min(self.K[o] for o in range(self.agent.opp_numactions))

        def clone(self):
            return copy.deepcopy(self)

    def __init__(self, no, game, N=15, episilon=0.1, alpha=0.01):
        super(KappaAgent, self).__init__(no, game, 'kapper')

        self.episilon = episilon
        self.alpha = alpha
        self.numstrategies = N
        self.particles = [KappaAgent.Particle(self, 1.0 / self.numstrategies) for _ in range(self.numstrategies)]
        self.strategy = None

    def act(self, exploration):
        if exploration and random.random() < self.episilon:
            self.strategy = random.choice(self.particles).strategy
        else:
            self.strategy = max(self.particles, key=(lambda x: x.val())).strategy
        return self.strategy.sample()

    def update(self, a, o, r):
        q = r + self.game.gamma * max(x.val() for x in self.particles)

        for p in self.particles:
            w = p.strategy.pi()[a] / self.strategy.pi()[a]
            p.K[o] += self.alpha * w * (q - p.K[o])

    def policy(self):
        return max(self.particles, key=(lambda x: x.val())).strategy.pi()

    def report(self):
        super(KappaAgent, self).report()
        eq = RandomAgent(self.no, self.game).strategy.pi()
        policies = ({'dist': np.linalg.norm(p.strategy.pi() - eq), 'pi': p.strategy, 'val': p.val()} for i, p in
                    enumerate(self.particles))
        policies = sorted(policies, key=lambda x: x['dist'])
        for i, p in enumerate(policies):
            print 'policy_{}:'.format(i), p