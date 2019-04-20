import numpy as np
import random
import sys
import pandas as pd
import math
from sklearn.base import BaseEstimator
from sklearn.utils.multiclass import class_distribution


class BOSSEnsemble(BaseEstimator):
    __author__ = "Matthew Middlehurst"

    """ Bag of SFA Symbols (BOSS)

    Bag of SFA Symbols Ensemble: implementation of BOSS from Schaffer :
    @article
    {schafer15boss,
     author = {Patrick Schäfer,
            title = {The BOSS is concerned with time series classification in the presence of noise},
            journal = {Data Mining and Knowledge Discovery},
            volume = {29},
            number= {6},
            year = {2015}
    }
    Overview: Input n series length m
    BOSS performs a gird search over a set of parameter values, evaluating each with a LOOCV. If then retains
    all ensemble members within 92% of the best. There are three primary parameters: 
            alpha: alphabet size
            w: window length
            l: word length.
    for any combination, a single BOSS slides a window length w along the series. The w length window is shortened to 
    an l length word through taking a Fourier transform and keeping the first l/2 complex coefficients. These l 
    coefficents are then discretised into alpha possible values, to form a word length l. A histogram of words for each 
    series is formed and stored. fit involves finding n histograms. 
    
    predict used 1 nearest neighbour with a bespoke distance function.  
    
    For the Java version, see
    https://github.com/TonyBagnall/uea-tsc/blob/master/src/main/java/timeseriesweka/classifiers/BOSS.java



    Parameters
    ----------
    randomised_ensemble   : boolean, turns the option to just randomise the ensemble members rather than cross validate (default=False) 
    random_ensemble_size: integer, if randomising, generate this number of base classifiers
    random_state    : integer or None, seed for random, integer, optional (default to no seed)
    dim_to_use      : integer >=0, the column of the panda passed to use, optional (default = 0)
    threshold       : double [0,1]. retain all classifiers within threshold% of the best one, optional (default =0.92)
    max_ensemble_size    : integer, retain a maximum number of classifiers, even if within threshold, optional (default = 500)
    wordLengths     : list of integers, search space for word lengths (default =100)
    alphabet_size    : range of alphabet sizes to try (default to single value, 4)
    
    Attributes
    ----------
    num_classes    : extracted from the data
    num_atts       : extracted from the data
    classifiers    : array of DecisionTree classifiers
    intervals      : stores indexes of the start and end points for all classifiers
    dim_to_use     : the column of the panda passed to use (can be passed a multidimensional problem, but will only use one)

    """

    def __init__(self,
                 randomised_ensemble=False,
                 random_ensemble_size=100,
                 random_state=None,
                 dim_to_use=0,
                 threshold=0.92,
                 max_ensemble_size=250,
                 wordLengths=[16, 14, 12, 10, 8],
                 alphabetSize=4
                 ):
        self.randomised_ensemble = randomised_ensemble
        self.ensemble_size = random_ensemble_size
        self.random_state = random_state
        random.seed(random_state)
        self.dim_to_use = dim_to_use
        self.threshold = threshold
        self.max_ensemble_size = max_ensemble_size

        self.seed = 0

        self.classifiers = []
        self.num_classes = 0
        self.classes_ = []
        self.class_dictionary = {}
        self.num_classifiers = 0
        self.series_length=0
        # For the multivariate case treating this as a univariate classifier
        # Parameter search values
        self.word_lengths = wordLengths
        self.norm_options = [True, False]
        self.alphabet_size = alphabetSize
        self.min_window = 10


    def fit(self, X, y):
        """Build an ensemble of BOSS classifiers from the training set (X, y), either through randomising over the para
         space to make a fixed size ensemble quickly or by creating a variable size ensemble of those within a threshold
         of the best
        Parameters
        ----------
        X : array-like or sparse matrix of shape = [n_samps, num_atts]
            The training input samples.  If a Pandas data frame is passed, the column _dim_to_use is extracted
        y : array-like, shape = [n_samples] or [n_samples, n_outputs]
            The class labels.

        Returns
        -------
        self : object
         """


        if isinstance(X, pd.DataFrame):
            if isinstance(X.iloc[0,self.dim_to_use],pd.Series):
                X = np.asarray([a.values for a in X.iloc[:,0]])
            else:
                raise TypeError("Input should either be a 2d numpy array, or a pandas dataframe containing Series objects")

        num_insts, self.series_length = X.shape
        self.num_classes = np.unique(y).shape[0]
        self.classes_ = class_distribution(np.asarray(y).reshape(-1, 1))[0][0]
#        self.classes_ = list(set(y))
        for index, classVal in enumerate(self.classes_):
            self.class_dictionary[classVal] = index


#        for index, classVal in enumerate(self.classes_):
#            self.class_dictionary[classVal] = index
        # Window length parameter space dependent on series length

        max_window_searches = self.series_length/4
        win_inc = (int)((self.series_length - self.min_window) / max_window_searches)
        if win_inc < 1: win_inc = 1

        if self.randomised_ensemble:
            random.seed(self.seed)

            while len(self.classifiers) < self.ensemble_size:
                word_len = self.word_lengths[random.randint(0, len(self.word_lengths) - 1)]
                win_size = self.min_window + win_inc * random.randint(0, max_window_searches)
                if win_size > max_window_searches: win_size = max_window_searches
                normalise = random.random() > 0.5

                boss = BOSSIndividual(win_size, self.word_lengths[word_len], self.alphabet_size, normalise)
                boss.fit(X, y)
                boss.clean()
                self.classifiers.append(boss)
        else:
            max_acc = -1
            min_max_acc = -1

            for i, normalise in enumerate(self.norm_options):
                for win_size in range(self.min_window, self.series_length+1, win_inc):
                    boss = BOSSIndividual(win_size, self.word_lengths[0], self.alphabet_size, normalise)
                    boss.fit(X, y)

                    bestAccForWinSize = -1

                    for n, word_len in enumerate(self.word_lengths):
                        if n > 0:
                            boss = boss.shortenBags(word_len)

                        correct = 0
                        for g in range(num_insts):
                            c = boss.train_predict(g)
                            if (c == y[g]):
                                correct += 1

                        accuracy = correct/num_insts
                        if (accuracy >= bestAccForWinSize):
                            bestAccForWinSize = accuracy
                            bestClassifierForWinSize = boss
                            bestWordLen = word_len

                    if self.include_in_ensemble(bestAccForWinSize, max_acc, min_max_acc, len(self.classifiers)):
                        bestClassifierForWinSize.clean()
                        bestClassifierForWinSize.setWordLen(bestWordLen)
                        bestClassifierForWinSize.accuracy = bestAccForWinSize
                        self.classifiers.append(bestClassifierForWinSize)

                        if bestAccForWinSize > max_acc:
                            max_acc = bestAccForWinSize

                            for c, classifier in enumerate(self.classifiers):
                                if classifier.accuracy < max_acc * self.threshold:
                                    self.classifiers.remove(classifier)

                        min_max_acc, minAccInd = self.worst_of_best()

                        if len(self.classifiers) > self.max_ensemble_size:
                            del self.classifiers[minAccInd]
                            min_max_acc, minAccInd = self.worst_of_best()

        self.num_classifiers = len(self.classifiers)

    def predict(self, X):
        return [self.classes_[np.argmax(prob)] for prob in self.predict_proba(X)]

    def predict_proba(self, X):
        if isinstance(X, pd.DataFrame):
            if isinstance(X.iloc[0,self.dim_to_use],pd.Series):
                X = np.asarray([a.values for a in X.iloc[:,0]])
            else:
                raise TypeError("Input should either be a 2d numpy array, or a pandas dataframe containing Series objects")

        sums = np.zeros((X.shape[0], self.num_classes))

        for i, clf in enumerate(self.classifiers):
            preds = clf.predict(X)
            for i in range(0,X.shape[0]):
                sums[i,self.class_dictionary.get(str(preds[i]))] += 1

        dists = sums / (np.ones(self.num_classes) * self.num_classifiers)
        return dists

    def include_in_ensemble(self, acc, maxAcc, minMaxAcc, size):
        if acc >= maxAcc * self.threshold:
            if size >= self.max_ensemble_size:
                return acc > minMaxAcc
            else:
                return True
        return False

    def worst_of_best(self):
        minAcc = -1;
        minAccInd = 0

        for c, classifier in enumerate(self.classifiers):
            if classifier.accuracy < minAcc:
                minAcc = classifier.accuracy
                minAccInd = c

        return minAcc, minAccInd

    def findEnsembleTrainAcc(self, X, y):
        num_inst = X.shape[0]
        results = np.zeros((2 + self.num_classes, num_inst + 1))
        correct = 0

        for i in range(num_inst):
            sums = np.zeros(self.num_classes)

            for n in range(len(self.classifiers)):
                sums[self.class_dictionary.get(self.classifiers[n].train_predict(i), -1)] += 1

            dists = sums / (np.ones(self.num_classes) * self.num_classifiers)
            c = dists.argmax()

            if c == self.class_dictionary.get(y[i], -1):
                correct += 1

            results[0][i+1] = self.class_dictionary.get(y[i], -1)
            results[1][i+1] = c

            for n in range(self.num_classes):
                results[2+n][i+1] = dists[n]

        results[0][0] = correct/num_inst
        return results


class BOSSIndividual:
    """ Single Bag of SFA Symbols (BOSS) classifier

    Bag of SFA Symbols Ensemble: implementation of BOSS from Schaffer :
    @article
    """
    def __init__(self, windowSize, wordLength, alphabetSize, norm):
        self.windowSize = windowSize
        self.wordLength = wordLength
        self.alphabetSize = alphabetSize
        self.norm = norm

        self.transform = BOSSTransform(windowSize, wordLength, alphabetSize, norm)
        self.transformedData = []
        self.classVals = []
        self.accuracy = 0

    def fit(self, X, y):
        self.transformedData = self.transform.fit(X)
        self.classVals = y

    def predict(self, X):
        num_insts, num_atts = X.shape
        classes = np.zeros(num_insts, dtype=np.int_)

        for i in range(num_insts):
            testBag = self.transform.transform_single(X[i, :])
            bestDist = sys.float_info.max
            nn = -1

            for n, bag in enumerate(self.transformedData):
                dist = self.BOSSDistance(testBag, bag, bestDist)

                if dist < bestDist:
                    bestDist = dist;
                    nn = self.classVals[n]

            classes[i] = nn

        return classes

    def train_predict(self, train_num):
        testBag = self.transformedData[train_num]
        bestDist = sys.float_info.max
        nn = -1

        for n, bag in enumerate(self.transformedData):
            if n == train_num:
                continue

            dist = self.BOSSDistance(testBag, bag, bestDist)

            if dist < bestDist:
                bestDist = dist;
                nn = self.classVals[n]

        return nn

    def BOSSDistance(self, bagA, bagB, bestDist):
        dist = 0

        for word, valA in bagA.items():
            valB = bagB.get(word, 0)
            dist += (valA-valB)*(valA-valB)

            if dist > bestDist:
                return sys.float_info.max

        return dist

    def shortenBags(self, wordLen):
        newBOSS = BOSSIndividual(self.windowSize, wordLen, self.alphabetSize, self.norm)
        newBOSS.transform = self.transform
        newBOSS.transformedData = self.transform.shorten_bags(wordLen)
        newBOSS.classVals = self.classVals

        return newBOSS

    def clean(self):
        self.transform.words = None

    def setWordLen(self, wordLen):
        self.wordLength = wordLen
        self.transform.wordLength = wordLen

class BOSSTransform():
    """ Boss Transform for whole series

    """
    def __init__(self, windowSize, wordLength, alphabetSize, norm):
        self.words = []
        self.breakpoints = []

        self.inverseSqrtWindowSize = 1 / math.sqrt(windowSize)
        self.windowSize = windowSize
        self.wordLength = wordLength
        self.alphabetSize = alphabetSize
        self.norm = norm

        self.num_insts = 0
        self.num_atts = 0

    def fit(self, X):
        self.num_insts, self.num_atts = X.shape
        self.breakpoints = self.MCB(X)

        bags = []

        for i in range(self.num_insts):
            dfts = self.MFT(X[i, :])
            bag = {}
            lastWord = -1

            words = []

            for window in range(dfts.shape[0]):
                word = self.createWord(dfts[window])
                words.append(word)
                lastWord = self.addToBag(bag, word, lastWord)

            self.words.append(words)
            bags.append(bag)

        return bags

    def transform_single(self, series):
        dfts = self.MFT(series)
        bag = {}
        lastWord = -1

        for window in range(dfts.shape[0]):
            word = self.createWord(dfts[window])
            lastWord = self.addToBag(bag, word, lastWord)

        return bag

    def MCB(self, X):
        numWindowsPerInst = math.ceil(self.num_atts / self.windowSize)
        dft = np.zeros((self.num_insts, numWindowsPerInst, int((self.wordLength / 2)*2)))

        for i in range(X.shape[0]):
            split = np.split(X[i, :], np.linspace(self.windowSize, self.windowSize*(numWindowsPerInst-1),
                                              numWindowsPerInst-1, dtype=np.int_))
            split[-1] = X[i, self.num_atts - self.windowSize:self.num_atts]

            for n, row in enumerate(split):
                dft[i, n] = self.DFT(row)

        totalNumWindows = self.num_insts * numWindowsPerInst
        breakpoints = np.zeros((self.wordLength, self.alphabetSize))

        for letter in range(self.wordLength):
            column = np.zeros(totalNumWindows)

            for inst in range(self.num_insts):
                for window in range(numWindowsPerInst):
                    column[(inst * numWindowsPerInst) + window] = round(dft[inst][window][letter] * 100) / 100

            column = np.sort(column)

            binIndex = 0
            targetBinDepth = totalNumWindows / self.alphabetSize

            for bp in range(self.alphabetSize - 1):
                binIndex += targetBinDepth
                breakpoints[letter][bp] = column[int(binIndex)]

            breakpoints[letter][self.alphabetSize - 1] = sys.float_info.max

        return breakpoints

    def DFT(self, series):
        length = len(series)
        outputLength = int(self.wordLength / 2)
        start = 1 if self.norm else 0

        std = np.std(series)
        if std == 0: std = 1
        normalisingFactor = self.inverseSqrtWindowSize / std

        dft = np.zeros(outputLength * 2)

        for i in range(start, start + outputLength):
            idx = (i - start) * 2

            for n in range(length):
                dft[idx] += series[n] * math.cos(2 * math.pi * n * i / length)
                dft[idx + 1] += -series[n] * math.sin(2 * math.pi * n * i / length)

        dft *= normalisingFactor

        return dft

    def DFTunnormed(self, series):
        length = len(series)
        outputLength = int(self.wordLength / 2)
        start = 1 if self.norm else 0

        dft = np.zeros(outputLength * 2)

        for i in range(start, start + outputLength):
            idx = (i - start) * 2

            for n in range(length):
                dft[idx] += series[n] * math.cos(2 * math.pi * n * i / length)
                dft[idx + 1] += -series[n] * math.sin(2 * math.pi * n * i / length)

        return dft

    def MFT(self, series):
        startOffset = 2 if self.norm else 0
        l = self.wordLength + self.wordLength % 2
        phis = np.zeros(l)

        for i in range(0, l, 2):
            half = -(i + startOffset)/2
            phis[i] = math.cos(2 * math.pi * half / self.windowSize);
            phis[i+1] = -math.sin(2 * math.pi * half / self.windowSize)

        end = max(1, len(series) - self.windowSize + 1)
        stds = self.calcIncrementalMeanStd(series, end)
        transformed = np.zeros((end, l))
        mftData = None

        for i in range(end):
            if i > 0:
                for n in range(0, l, 2):
                    real1 = mftData[n] + series[i + self.windowSize - 1] - series[i - 1]
                    imag1 = mftData[n + 1]
                    real = real1 * phis[n] - imag1 * phis[n + 1]
                    imag = real1 * phis[n + 1] + phis[n] * imag1
                    mftData[n] = real
                    mftData[n + 1] = imag
            else:
                mftData = self.DFTunnormed(series[0:self.windowSize])

            normalisingFactor = (1 / stds[i] if stds[i] > 0 else 1) * self.inverseSqrtWindowSize;
            transformed[i] = mftData * normalisingFactor;

        return transformed

    def calcIncrementalMeanStd(self, series, end):
        means = np.zeros(end)
        stds = np.zeros(end)

        sum = 0
        squareSum = 0

        for ww in range(self.windowSize):
            sum += series[ww]
            squareSum += series[ww] * series[ww]

        rWindowLength = 1 / self.windowSize
        means[0] = sum * rWindowLength
        buf = squareSum * rWindowLength - means[0] * means[0]
        stds[0] = math.sqrt(buf) if buf > 0 else 0

        for w in range(1, end):
            sum += series[w + self.windowSize - 1] - series[w - 1]
            means[w] = sum * rWindowLength
            squareSum += series[w + self.windowSize - 1] * series[w + self.windowSize - 1] - series[w - 1] * series[w - 1]
            buf = squareSum * rWindowLength - means[w] * means[w]
            stds[w] = math.sqrt(buf) if buf > 0 else 0

        return stds

    def createWord(self, dft):
        word = BitWord()

        for i in range(self.wordLength):
            for bp in range(self.alphabetSize):
                if dft[i] <= self.breakpoints[i][bp]:
                    word.push(bp)
                    break

        return word

    def shorten_bags(self, wordLen):
        newBags = []

        for i in range(self.num_insts):
            bag = {}
            lastWord = -1

            for n, word in enumerate(self.words[i]):
                newWord = BitWord(word = word.word, length = word.length)
                newWord.shorten(16 - wordLen)
                lastWord = self.addToBag(bag, newWord, lastWord)

            newBags.append(bag)

        return newBags;

    def addToBag(self, bag, word, lastWord):
        if word.word == lastWord:
            return lastWord

        if word.word in bag:
            bag[word.word] += 1
        else:
            bag[word.word] = 1

        return word.word

class BitWord:

    def __init__(self, word = np.int_(0), length = 0):
        self.word = word
        self.length = length

    def push(self, letter):
        self.word = (self.word << 2) | letter
        self.length += 1

    def shorten(self, amount):
        self.word = self.rightShift(self.word,amount*2)
        self.length -= amount

    def wordList(self):
        wordList = []
        shift = 32-(self.length*2)

        for i in range(self.length-1, -1, -1):
            wordList.append(self.rightShift(self.word << shift, 32-2))
            shift += 2

        return wordList

    def rightShift(self, left, right):
        return (left % 0x100000000) >> right