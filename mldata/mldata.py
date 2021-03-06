"""
Tools for loading, preprocessing, formatting, and partitioning csv-formatted
datasets for ML applications. These tools can be used by a variety of models to
quickly convert diverse datasets to appropriate formats for learning.
"""
import os
import copy
import logging
import argparse
import operator
import itertools

import numpy as np
import pandas as pd
import scipy as sp
import seaborn as sns
from sklearn import preprocessing

from oset import OrderedSet


class BadFeatureConfig(Exception):
    """Raise when bad feature configuration file is found."""
    pass


class FeatureGuide(object):
    """Parse and represent fields of a feature guide."""

    _extension = '.fguide'

    """Guide to feature configuration file field letters."""
    config_guide = {
        't': 'target',
        'i': 'index',
        'k': 'key',
        'e': 'entities',
        'c': 'categoricals',
        'r': 'real_valueds'
    }

    sections = tuple(config_guide.values())
    other_sections = ('target', 'index')
    feature_sections = tuple(set(sections) - set(other_sections))

    # We use slots here not so much for efficiency as for documentation.
    __slots = [field_name for field_name in sections]
    __slots.append('fname')
    __slots.append('comments')

    @classmethod
    def add_extension_if_needed(cls, fname):
        if not fname.endswith(cls._extension):
            fname += cls._extension
        return fname

    @classmethod
    def from_name_lists(cls, fname, **name_lists):
        rows = []
        rows.append('# Generated programmaticaly from name lists.')
        rows.append('#\n')
        for letter, section_name in cls.config_guide.items():
            names = name_lists.get(section_name, [])
            as_string = '%s:%s;' % (letter, ','.join(names))
            rows.append(as_string)

        fname = cls.add_extension_if_needed(fname)
        with open(fname, 'w') as f:
            f.write('\n'.join(rows))

        return cls(fname)

    @classmethod
    def parse_config(cls, fname):
        """Parse the given configuration file and return a dict of
        {field_letter: list_of_field_names_parsed}.
        """
        with open(fname) as f:
            lines = [l.strip() for l in f.read().split('\n') if l.strip()]

        comments = [l.replace('#', '').strip()
                    for l in lines if l.startswith('#')]
        lines = [l for l in lines if not l.startswith('#')]

        # We use a simple state-machine approach to the parsing
        # in order to deal with multi-line sections.
        parsing = False
        keys = cls.config_guide.keys()
        vars = {var: [] for var in keys}
        for line in lines:
            if not parsing:
                k, csv = line.split(':')
            else:
                csv = line

            vars[k].extend([val.strip() for val in csv.split(',')])
            parsing = not line.endswith(';')
            if not parsing:
                vars[k][-1] = vars[k][-1][:-1]  # remove semi-colon

        # Remove whitespace strings. These may have come from something like:
        # c: this, , that;
        for k in keys:
            vars[k] = [val for val in vars[k] if val]  # already stripped

        return comments, vars

    def restore(self):
        """Parse the configuration and update instance variables to match."""
        self.comments, vars = self.parse_config(self.fname)

        # Sanity checks.
        num_targets = len(vars['t'])
        if num_targets != 1:
            raise BadFeatureConfig(
                'feature config should specify 1 target; got %d; check for'
                'the semi-colon at the end of the t:<target> line' % num_targets)

        num_entity = len(vars['e'])
        if not num_entity:
            raise BadFeatureConfig('0 entity variables given; need at least 1')

        # num_features = len(vars['c']) + len(vars['r'])
        # if not num_features > 0:
        #     raise BadFeatureConfig('no predictors specified')

        # Store extracted field names as instance variables.
        logging.info('read the following feature guide:')
        for k, field_name in self.config_guide.items():
            logging.info('%s: %s' % (field_name, ', '.join(vars[k])))

            # convert to OrderedSet before setting attribute
            setattr(self, field_name, OrderedSet(vars[k]))

        # Extract target variable from its list and store solo.
        self.target = self.target[0]

    def save(self, savedir='.', fname=None):
        """Save the feature guide to the given directory. The basename of the
        file read to create the feature guide is used by default. This can be
        overwritten by passing `fname`.

        Args:
            savedir (str): The directory to save the config file to. Defaults
                to the current working directory.
            fname (str): Optional file name to save the feature guide to. Any
                extension will be removed and replaced with ".conf". The
                basename of the file is used by default.
        """
        # Build up the file path to write to.
        dirpath = os.path.abspath(savedir)
        if fname is None:
            fname = os.path.basename(self.fname)

        name = os.path.splitext(fname)[0]
        path = os.path.join(dirpath, name + '.conf')

        # Put all comments and attributes into string formats.
        lines = ['# %s' % comment for comment in self.comments]
        lines.append('')
        for letter, section in self.config_guide.items():
            names = getattr(self, section)
            if names:
                if isinstance(names, basestring):
                    line = '%s: %s;' % (letter, names)
                else:
                    line = '%s: %s;' % (letter, ', '.join(names))
                lines.append(line)

        # Write the config.
        with open(path, 'w') as f:
            f.write('\n'.join(lines))

    def __init__(self, fname):
        """Read the feature guide and parse out the specification.

        The expected file format is the following:

            t:<target>;
            i:<single index field name, if one exists>;
            k:<comma-separated fields that comprise a unique key>;
            e:<comma-separated categorical entity names>;
            c:<comma-separated categorical variable names>;
            r:<comma-separated real-valued variable names>;

        Whitespace is ignored, as are lines that start with a "#" symbol. Any
        variables not included in one of the three groups is ignored. We assume
        the first two categorical variables are the user and item ids.

        Args:
            fname (str): Path of the file containing the feature guide.

        Stores instance variables for each of the field areas under the names in
        FeatureGuide.config_guide.
        """
        self.fname = os.path.abspath(fname)
        self.restore()

    def __repr__(self):
        return '%s("%s")' % (self.__class__.__name__, self.fname)

    def __str__(self):
        return '\n'.join([
            'target: %s' % self.target,
            'index: %s' % ', '.join(self.index),
            'key: %s' % ', '.join(self.key),
            'entities: %s' % ', '.join(self.entities),
            'categoricals: %s' % ', '.join(self.categoricals),
            'real-valueds: %s' % ', '.join(self.real_valueds)
        ])

    def __eq__(self, other):
        for name in self.sections:
            mine = getattr(self, name)
            yours = getattr(other, name)
            if mine != yours:
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def feature_names(self):
        return list(reduce(  # Intersection of all feature section names.
                lambda s1, s2: s1 | s2,
                [getattr(self, attr) for attr in self.feature_sections]))

    @property
    def all_names(self):
        return self.feature_names + [self.target] + list(self.index)

    def remove(self, name):
        """Remove a feature from all sections of the guide where it appears.
        This is disallowed for the target and features in the key.

        Args:
            name (str): The name of the feature to remove.
        Raises:
            AttributeError: if the name is in non-feature sections or the key.
            KeyError: if the name is not in any sections.

        """
        if name in self.other_sections:
            raise AttributeError('cannot remove feature from sections: %s' % (
                ', '.join(self.other_sections)))
        elif name in self.key:
            raise AttributeError('cannot remove features in key')

        # Check all other sections and remove from each where it appears.
        removed = 0
        for section in self.feature_sections:
            try:
                getattr(self, section).remove(name)
                removed += 1
            except KeyError:
                pass

        if not removed:
            raise KeyError("feature '%s' not in feature guide" % name)

    def union(self, other, inplace=True):
        """Perform a per-section union of all sections (including comments) and
        return a new feature guide with the resulting sections. This requires
        both sections have the same target.

        Args:
            other (FeatureGuide): The feature guide to union with.
        Return:
            union (FetaureGuide): New instance with unioned sections.
        """
        if self.target != other.target:
            raise ValueError('target mismatch (%s != %s)' % (
                self.target, other.target))

        union = self if inplace else copy.deepcopy(self)

        sections = [name for name in self.sections if name != 'target']
        for name in sections:
            mine = getattr(union, name)
            yours = getattr(other, name)
            setattr(union, name, mine | yours)

        return union

    @staticmethod
    def union_all(feature_guides):
        """Return union of all FeatureGuide objects in iterable. This is more
        efficient than using FeatureGuide.union repeatedly since it only makes
        one copy.

        Args:
            feature_guides (iterable of FeatureGuide)
        Return:
            union (FeatureGuide): A new FeatureGuide where each section is the
                union of the same section for all FeatureGuide objects in the
                iterable.
        Raises:
            ValueError: if any of the targets do not match.
        """
        if len(set(fg.target for fg in feature_guides)) != 1:
            raise ValueError('target is not the same in all FeatureGuides')

        union = copy.deepcopy(feature_guides[0])
        others = feature_guides[1:]
        sections = [name for name in union.sections if name != 'target']
        for name in sections:
            getattr(union, name).union(*[getattr(fg, name) for fg in others])

        return union


"""
A dataset can exist in several different forms. For now, we assume one of two
forms:

    1.  Complete dataset in one file.
    2.  Separate train and test files with identical fields/indices/etc.

We allow the dataset to be initialized from either format and require an
accompanying config file that specifies the fields of the dataset. Since it may
be possible that other forms exist (e.g. with a hold-out set) we use a factory
to load the datasets. By making the first argument to the factory an optional
iterable, we can initialize differently based on the number of filenames
present.

TODO: not actually using a factory yet.
"""
class Dataset(object):
    """Represent a complete dataset existing in one file."""

    # Useful for train/test splits, which are accomplished by passing operations
    # performed on columns of data.
    ops = type('OpContainer', tuple(), {
        'lt': operator.lt,
        'gt': operator.gt,
        'le': operator.le,
        'ge': operator.ge,
        'eq': operator.eq,
        'ne': operator.ne
    })


class PandasDataset(Dataset):

    @staticmethod
    def index_from_feature_guide(fguide):
        """Return an appropriate index column name based on the feature guide
        -- acording to the following rules:

        1.  We should use the index as the index if it is present.
        2.  If the index is not present, we should use the key as the index
            only if none of those fields are also used as features.
        3.  If some of those fields are used as features, we should make a new
            index and add it to the feature guide; in this case, return None.
        """
        if fguide.index:
            return list(fguide.index)
        elif (fguide.key and
              (fguide.key - fguide.feature_names) == fguide.key):
                return list(fguide.key)
        else:
            return None

    def index_colname(self):
        return self.index_from_feature_guide(self.fguide)

    @staticmethod
    def read_using_fguide(fname, fguide):
        """Read a DataFrame from the file. Load only the columns that show up
        in the feature guide and set the index intelligently using
        `PandasDataset.index_colname`.

        Currently this assumes csv files.

        Args:
            fname (str): Name of the file to read the DataFrame from.
            fguide {FeatureGuide | str}: The feature guide to extract the index
                and the list of columns from. This can also be a string, in
                which case it is interpreted as the name of a file, in which
                case we attempt to instantiate a `FeatureGuide` from it.
        Return:
            df (pd.DataFrame): DataFrame read from the file.
        """
        if isinstance(fguide, basestring):
            fguide = FeatureGuide(fguide)

        kwargs = {
            'index_col': PandasDataset.index_from_feature_guide(fguide),
            'usecols': fguide.all_names
        }
        return pd.read_csv(fname, **kwargs)

    def read(self, fname):
        """Read a DataFrame from the file. Load only the columns that show up
        in the feature guide and set the index intelligently using
        `PandasDataset.index_colname`.

        Currently this assumes csv files.

        Args:
            fname (str): Name of the file to read the DataFrame from.
        Return:
            df (pd.DataFrame): DataFrame read from the file.
        """
        return self.read_using_fguide(fname, self.fguide)

    @staticmethod
    def write_using_fguide(df, fname, fguide):
        index_col = PandasDataset.index_from_feature_guide(fguide)
        kwargs = {'index': index_col is not None}
        df.to_csv(fname, **kwargs)

    def map_column_to_index(self, entity):
        raise NotImplementedError

    def make_entities_contiguous(self):
        for entity in self.fguide.entities:
            self.map_column_to_index(entity)


class PandasFullDataset(PandasDataset):

    def __init__(self, fname, config_file):
        """Load the feature configuration and then load the columns present in
        the feature config.
        """
        self.fguide = FeatureGuide(config_file)
        self.fname = os.path.abspath(fname)
        self.dataset = self.read(self.fname)

        # Instance variables to store metadata generated during transformations.
        self.column_maps = {}  # mapping from one space to another
        self.imputations = {}  # imputing missing values
        self.scalers = {}      # scaling column values

    @property
    def reals(self):
        return self.dataset[list(self.fguide.real_valueds)]

    @property
    def categoricals(self):
        return self.dataset[list(self.fguide.categoricals)]

    @property
    def entities(self):
        return self.dataset[list(self.fguide.entities)]

    @property
    def key(self):
        return self.dataset[list(self.fguide.key)]

    def map_column_to_index(self, col):
        """Map values in column to a 0-contiguous index. This enables use of
        these attributes as indices into an array (for bias terms, for
        instance). This method changes the ids in place, producing an (new_id,
        orig_id) dict which is stored in the `column_maps` instance variable.

        This operation is idempotent.

        Args:
            key (str): Column name with ids to map.
        """
        if col in self.column_maps:
            return

        # First construct the map from original ids to new ones.
        ids = self.dataset[col].unique()
        n = len(ids)
        idmap = dict(itertools.izip(ids, xrange(n)))

        # Next use the map to conver the ids in-place.
        self.dataset[col] = self.dataset[col].apply(lambda _id: idmap[_id])

        # Now swap key for value in the idmap to provide a way to convert back.
        reverse_map = {val: key for key, val in idmap.iteritems()}
        self.column_maps[col] = reverse_map

    def unmap_column_from_index(self, col, not_mapped='raise'):
        try:
            reverse_map = self.column_maps[col]
        except KeyError:
            if not_mapped == 'raise':
                raise ValueError('column %s was not mapped to an index' % col)
            elif not_mapped == 'warn':
                # TODO: implement warning
                pass

        self.dataset[col] = self.dataset[col].apply(
            lambda _id: reverse_map[_id])
        del self.column_maps[col]

    def remove_feature(self, name):
        """Remove the given feature from the feature guide and then from the
        dataset.

        Args:
            name (str): Name of the feature to remove.
        Raises:
            AttributeError: if the name is in non-feature sections or the key
                section of the feature guide.
            KeyError: if the name is not in feature guide or not in the dataset.
        """
        logging.info('removing feature %s' % name)
        self.fguide.remove(name)
        self.dataset.pop(name)

    def column_is_all_null(self, column):
        return self.dataset[column].isnull().sum() == len(self.dataset)

    def verify_columns_in_dataset(self, columns):
        """Ensure all columns are present in the dataset before doing some
        operation to avoid side effects or the need for rollback.
        """
        all_cols = self.dataset.columns
        for col in columns:
            if not col in all_cols:
                raise KeyError("column '%s' not in dataset" % col)

    def impute(self, columns, method='median', all_null='raise'):
        """Perform missing value imputation for the given columns using the
        specified `pandas.DataFrame` method for the fill value. All NaN values
        in the columns will be replaced with this value.

        Args:
            columns (iterable of str): Column names to perform missing value
                imputation on.
            method (str): Name of the `pandas.DataFrame` method to use to
                compute the fill value.
            all_null (str): One of {'drop', 'raise', 'ignore'}, this defines the
                action taken when a column with only missing values is
                encountered. If drop, the entire column is dropped. If raise, a
                ValueError is raised. If ignore, the column is ignored.
        Raises:
            KeyError: if any of the column names are not in the dataset.
            ValueError: if 'raises is specified for `all_null` and an all null
                column is encountered.

        """
        # Ensure all_null is one of the valid choices.
        allowed = {'drop', 'raise', 'ignore'}
        if all_null not in allowed:
            raise ValueError(
                'all_null must be one of: %s' % ', '.join(allowed))

        self.verify_columns_in_dataset(columns)

        # If all_null='raise', check all columns first to avoid side effects.
        if all_null == 'raise':
            for col in columns:
                if self.column_is_all_null(col):
                    raise ValueError("all null column '%s'" % col)

        for col in columns:
            if self.column_is_all_null(col):
                if all_null == 'drop':
                    self.remove_feature(col)
                    logging.info("all null column '%s' was dropped" % col)
                    continue
                # Already checked all_null == 'raise'
                else:
                    logging.info("all null column '%s' ignored" % col)

            # Compute fill value and fill all NaN values.
            column = self.dataset[col]
            fill_value = getattr(column, method)()
            self.dataset[col] = column.fillna(fill_value)

            # Store fill_value imputed.
            self.imputations[col] = fill_value

    def impute_reals(self, **kwargs):
        self.impute(self.fguide.real_valueds, **kwargs)

    def scale(self, columns):
        """Z-score scale the given columns IN-PLACE, storing the scalers used in
        the `scalers` instance variable. The scaling can be reversed using
        `unscale`.

        Args:
            columns (iterable of str): Column names to scale.
        Raises:
            KeyError: if any of the column names are not in the dataset.

        """
        self.verify_columns_in_dataset(columns)

        for col in columns:
            # First ensure the column has not already been scaled.
            if col in self.scalers:
                scaler, scaled = self.scalers[col]
            else:
                scaler = preprocessing.StandardScaler()
                scaled = False

            if not scaled:
                self.scalers[col] = (scaler, True)
                self.dataset[col] = scaler.fit_transform(self.dataset[[col]])

    def scale_reals(self):
        if self.fguide.real_valueds:
            self.scale(self.fguide.real_valueds)

    def unscale(self, columns):
        """Reverse the Z-score scaling on the given columns IN-PLACE. If any of
        the given columns have not been scaled, they are ignored.

        Args:
            columns (iterable of str): Column names to unscale.
        Raises:
            KeyError: if any of the column names are not in the dataset.

        """
        self.verify_columns_in_dataset(columns)

        for col in columns:
            scaler, scaled = self.scalers.get(col, (0, 0))
            if not scaled:
                logging.info("column '%s' has not been scaled, ignoring" % col)
                continue

            self.dataset.loc[:, col] = \
                scaler.inverse_transform(self.dataset[col])
            self.scalers[col][1] = False

    def unscale_reals(self):
        if self.fguide.real_valueds:
            self.unscale(self.fguide.real_valueds)

    def preprocess(self, impute=True):
        """Return preprocessed (X, y, eid) pairs for the train and test sets.

        Preprocessing includes:

        1.  Map all entity IDs to a 0-contiguous range.
        2.  Z-score scale the real-valued features.
        3.  One-hot encode the categorical features (including entity IDs).

        This function tries to be as general as possible to accomodate learning by
        many models. As such, there are a variety of return values:

        1.  X: feature vector matrix (first categorical, then real-valued)
        2.  y: target values (unchanged from input)
        3.  eids: entity IDs as a numpy ndarray
        4.  indices: The indices of each feature in the encoded X matrix.
        5.  nents: The number of unique entities for each entity.

        """
        eids = {}
        for entity in self.fguide.entities:
            self.map_column_to_index(entity)
            eids[entity] = self.dataset[entity].values

        # Z-score scaling of real-valued features.
        self.impute_reals()
        self.scale_reals()
        nreal = len(self.fguide.real_valueds)

        # One-hot encoding of entity and categorical features.
        cats_and_ents = list(self.fguide.entities | self.fguide.categoricals)
        all_cats = self.dataset[cats_and_ents]
        encoder = preprocessing.OneHotEncoder()
        encoded_cats = encoder.fit_transform(all_cats)

        # Create a feature map for decoding one-hot encoding.
        ncats_and_ents = encoder.active_features_.shape[0]
        nf = ncats_and_ents + nreal

        # Count entities.
        logging.info('after one-hot encoding, found # unique values:')
        counts = np.array([
            all_cats[cats_and_ents[i]].unique().shape[0]
            for i in range(len(cats_and_ents))
        ])

        # Assemble map to new feature indices using counts.
        indices = zip(cats_and_ents, np.cumsum(counts))
        for attr, n_values in zip(self.fguide.entities, counts):
            logging.info('%s: %d' % (attr, n_values))

        # Add in real-valued feature indices.
        last_cat_index = indices[-1][1]
        indices += zip(self.fguide.real_valueds,
                       range(last_cat_index + 1, nf + 1))

        # How many entity and categorical features do we have now?
        nents = dict(indices)[self.fguide.entities[-1]]
        ncats = ncats_and_ents - nents
        nf = ncats_and_ents + nreal

        n_ent_names = len(self.fguide.entities)
        ent_idx = range(n_ent_names)
        cat_idx = range(n_ent_names, len(cats_and_ents))
        nactive_ents = sum(encoder.n_values_[i] for i in ent_idx)
        nactive_cats = sum(encoder.n_values_[i] for i in cat_idx)

        logging.info('number of active entity features: %d of %d' % (
            nents, nactive_ents))
        logging.info('number of active categorical features: %d of %d' % (
            ncats, nactive_cats))
        logging.info('number of real-valued features: %d' % nreal)
        logging.info('Total of %d features after encoding' % nf)

        # Put all features together.
        X = sp.sparse.hstack((encoded_cats, self.reals))\
            if nreal else encoded_cats
        y = self.dataset[self.fguide.target].values
        return X.tocsr(), y, eids, indices, nents

    def split(self, train_mask, test_mask):
        """Split the dataset based on a row-wise mask. This allows users to
        perform comparisons with fields of the DataFrame in the function call,
        like so:

        dset = PandasDataset(...)
        train, test = dset.split(dset.dataset.time < 2, dset.dataset.time == 2)

        """
        train = self.dataset.loc[train_mask]
        test = self.dataset.loc[test_mask]
        return PandasTrainTestSplit.from_dfs(train, test, self.fguide)

    def split_loop(self, col, train_cmp, test_cmp, window=None):
        return PandasDatasetSplitter(self, col, train_cmp, test_cmp, window=None)


class PandasDatasetRandomBinarySplitter(object):
    """Produces random binary splits of the rows, s.t. P% is train and (1-P)% test."""

    def __init__(self, dataset, p):
        self.dataset = dataset
        self.p = p

    def split(self):
        index = self.dataset.dataset.index
        N = index.shape[0]
        ntrain = int(N * self.p + 1)

        shuffled = np.random.shuffle(index)
        train_indices = shuffled[:ntrain]
        test_indices = shuffled[ntrain:]

        train = self.dataset.ix[train_indices]
        test = self.dataset.ix[test_indices]
        return PandasTrainTestSplit.from_dfs(train, test, self.dataset.fguide)


class PandasDatasetSplitter(object):
    """Iterator for all possible train/test splits using given col & ops."""

    def __init__(self, dataset, colname, train_cmp, test_cmp, window=None):
        """
        Args:
            dataset (PandasFullDataset): The dataset to produce
                train/test splits from.
            colname (str): Name of the column to use for splitting
                comparisons.
            train_cmp (function): Comparison function to use for
                getting the subset to be used for training data.
            test_cmp (function): Comparison function to use for
                getting the subset to be used for testing data.
            window (int): Limit on number of previous units to include in the
                training set. None by default.
        """
        self.dataset = dataset
        self.colname = colname
        self.train_cmp = train_cmp
        self.test_cmp = test_cmp
        self.window = window

    @property
    def column(self):
        return self.dataset.dataset[self.colname]

    @property
    def unique_values(self):
        return self.column.unique()

    @property
    def np_splits(self):
        return self.unique_values.shape[0]

    def __iter__(self):
        column = self.column
        global_min_val = min(self.unique_values)
        for val in self.unique_values:
            min_val = (global_min_val if self.window is None else
                       val - self.window)
            constraint = column >= min_val
            train_mask = self.train_cmp(column, val) & constraint
            test_mask = self.test_cmp(column, val)
            yield self.dataset.split(train_mask, test_mask)

    def iteritems(self, errors='log'):
        """Iterate over all possible splits, returning each in a tuple with its
        associated value.

        Args:
            errors (str): One of {'raise', 'log', 'ignore'}, this specifies how
                errors that occur during production of TrainTestSplit objects
                should be handled.
                If "raise": simply let errors propogate.
                If "log": log the error with level `logging.ERROR`.
                If "ignore": log with level `logging.INFO`.
        Return:
            generator of (val, TrainTestSplit) pairs.
        """
        column = self.column
        for val in self.unique_values:
            try:
                split = self.dataset.split(
                    self.train_cmp(column, val), self.test_cmp(column, val))
                yield (val, split)
            except Exception as err:
                if errors == 'raise':
                    raise
                elif errors == 'log':
                    logging.error(str(err))
                else:
                    logging.info(str(err))

    def __getitem__(self, val):
        if val not in self.unique_values:
            raise ValueError(
                'value {} not in column {}'.format(val, self.colname))

        column = self.column
        return self.dataset.split(
            self.train_cmp(column, val), self.test_cmp(column, val))


class PandasTrainTestSplit(PandasDataset):

    @classmethod
    def from_files(cls, train_fname, test_fname, config_file):
        """Load the datasets and the feature configuration from files."""
        fguide = FeatureGuide(config_file)

        # Set index based on the feature guide and load only needed columns.
        index_col = cls.index_from_feature_guide(fguide)
        kwargs = dict(usecols=fguide.all_names, index_col=index_col)
        dset = cls(pd.read_csv(train_fname, **kwargs),
                   pd.read_csv(test_fname, **kwargs),
                   fguide)

        # Store pathnames as instance variables.
        dset.train_fname = os.path.abspath(train_fname)
        dset.test_fname = os.path.abspath(test_fname)
        return dset

    @classmethod
    def from_dfs(cls, train_df, test_df, fguide):
        """Initialize a dataset from DataFrame objects and a FeatureGuide
        already in memory.
        """
        # We only need to use columns that show up in the config file.
        usecols = fguide.all_names
        index_col = cls.index_from_feature_guide(fguide)

        if index_col is None:
            train = train_df.reset_index(drop=True)[usecols]
            test = test_df.reset_index(drop=True)[usecols]
        else:
            train = train_df.set_index(index_col)[usecols]
            test = test_df.set_index(index_col)[usecols]

        return cls(train, test, copy.deepcopy(fguide))

    def __init__(self, train_df, test_df, fguide):
        # Sanity checks
        train_nsamples, train_ncols = train_df.shape[:2]
        test_nsamples, test_ncols = test_df.shape[:2]

        if train_nsamples == 0:  # must have training data
            raise ValueError('training set has 0 samples')
        if test_nsamples == 0:   # must have test data
            raise ValueError('testing set has 0 samples')
        if train_ncols != test_ncols:  # columns must match
            raise ValueError('# train cols != # test cols (%d != %d)' % (
                train_ncols, test_ncols))

        self.train = train_df
        self.test = test_df
        self.fguide = fguide

        # Instance variables to store metadata generated during transformations.
        self.column_maps = {}  # mapping from one space to another
        self.imputations = {}  # imputing missing values
        self.scalers = {}      # scaling column values

    def map_column_to_index(self, col):
        """Map values in column to a 0-contiguous index. This enables use of
        these attributes as indices into an array (for bias terms, for
        instance). This method changes the ids in place, producing an (new_id,
        orig_id) dict which is stored in the `column_maps` instance variable.

        Args:
            key (str): Column name with ids to map.
        """
        if col in self.column_maps:
            return

        # First construct the map from original ids to new ones.
        ids = pd.concat((self.train[col], self.test[col])).unique()
        n = len(ids)
        idmap = dict(itertools.izip(ids, xrange(n)))

        # Next use the map to convert the ids in-place.
        self.train.loc[:, col] = self.train[col].apply(lambda _id: idmap[_id])
        self.test.loc[:, col] = self.test[col].apply(lambda _id: idmap[_id])

        # Now swap key for value in the idmap to provide a way to convert back.
        reverse_map = {val: key for key, val in idmap.iteritems()}
        self.column_maps[col] = reverse_map

    def unmap_column_from_index(self, col, not_mapped='raise'):
        try:
            reverse_map = self.column_maps[col]
        except KeyError:
            if not_mapped == 'raise':
                raise ValueError('column %s was not mapped to an index' % col)
            elif not_mapped == 'warn':
                # TODO: implement warning
                pass

        # Next use map to convert back to original ids in-place.
        self.train.loc[:, col] = self.train[col].apply(
            lambda _id: reverse_map[_id])
        self.test.loc[:, col] = self.test[col].apply(
            lambda _id: reverse_map[_id])
        self.dataset[col] = self.dataset[col].apply(
            lambda _id: reverse_map[_id])

        # Finally, remove the reverse id map from the dict of column maps.
        del self.column_maps[col]

    def remove_feature(self, name):
        """Remove the given feature from the feature guide and then from the
        dataset. The feature is removed from both train and test DataFrame
        objects in-place.

        Args:
            name (str): Name of the feature to remove.
        Raises:
            AttributeError: if the name is in non-feature sections or the key
                section of the feature guide.
            KeyError: if the name is not in feature guide or not in the dataset.
        """
        logging.info('removing feature %s' % name)
        self.fguide.remove(name)
        self.train.pop(name)
        self.test.pop(name)

    @staticmethod
    def df_column_is_all_null(df, column):
        """Return True if the given column has only NaN values, else False."""
        return df[column].isnull().sum() == len(df)

    def train_column_is_all_null(self, column):
        """Return True if the given column has only NaN values in the training
        set, else False.
        """
        return self.df_column_is_all_null(self.train, column)

    def verify_columns_in_dataset(self, columns):
        """Ensure all columns are present in the dataset before doing some
        operation to avoid side effects or the need for rollback. We assume here
        that both train and test DataFrame objects share the same column set.
        """
        all_cols = self.train.columns
        for col in columns:
            if not col in all_cols:
                raise KeyError("column '%s' not in dataset" % col)

    def impute(self, columns, method='median', all_null='raise'):
        """Perform missing value imputation for the given columns using the
        specified `pandas.DataFrame` method for the fill value. All NaN values
        in the columns will be replaced with this value.

        In order to avoid data leakage, the fill value is computed from the
        training set and used to fill in missing values in both the train and
        test sets.

        Args:
            columns (iterable of str): Column names to perform missing value
                imputation on.
            method (str): Name of the `pandas.DataFrame` method to use to
                compute the fill value.
            all_null (str): One of {'drop', 'raise', 'ignore'}, this defines the
                action taken when a column with only missing values is
                encountered. If drop, the entire column is dropped. If raise, a
                ValueError is raised. If ignore, the column is ignored.
        Raises:
            KeyError: if any of the column names are not in the dataset.
            ValueError: if 'raises is specified for `all_null` and an all null
                column is encountered.

        """
        # Ensure all_null is one of the valid choices.
        allowed = {'drop', 'raise', 'ignore'}
        if all_null not in allowed:
            raise ValueError(
                'all_null must be one of: %s' % ', '.join(allowed))

        self.verify_columns_in_dataset(columns)

        # If all_null='raise', check all columns first to avoid side effects.
        if all_null == 'raise':
            for col in columns:
                if self.train_column_is_all_null(col):
                    raise ValueError("all null column '%s'" % col)

        for col in columns:
            if self.train_column_is_all_null(col):
                if all_null == 'drop':
                    self.remove_feature(col)
                    logging.info("all null column '%s' was dropped" % col)
                    continue
                # Already checked all_null == 'raise'
                else:
                    logging.info("all null column '%s' ignored" % col)

            # Compute fill value and fill all NaN values.
            train_column = self.train[col]
            fill_value = getattr(train_column, method)()
            self.train.loc[:, col] = train_column.fillna(fill_value)
            self.test.loc[:, col] = self.test[col].fillna(fill_value)

            # Store fill_value imputed.
            self.imputations[col] = fill_value

    def impute_reals(self, **kwargs):
        self.impute(self.fguide.real_valueds, **kwargs)

    def scale(self, columns):
        """Z-score scale the given columns IN-PLACE, storing the scalers used in
        the `scalers` instance variable. The scaling can be reversed using
        `unscale`.

        In order to avoid data leakage, the scaling parameters are computed from
        the training set and used to scale both the train and the test sets.

        Args:
            columns (iterable of str): Column names to scale.
        Raises:
            KeyError: if any of the column names are not in the dataset.

        """
        self.verify_columns_in_dataset(columns)

        for col in columns:
            # First ensure the column has not already been scaled.
            if col in self.scalers:
                scaler, scaled = self.scalers[col]
            else:
                scaler = preprocessing.StandardScaler()
                scaled = False

            if not scaled:
                self.scalers[col] = (scaler, True)
                self.train.loc[:, col] = scaler.fit_transform(self.train[[col]])
                self.test.loc[:, col] = scaler.transform(self.test[[col]])

    def scale_reals(self):
        if self.fguide.real_valueds:
            self.scale(self.fguide.real_valueds)

    def unscale(self, columns):
        """Reverse the Z-score scaling on the given columns IN-PLACE. If any of
        the given columns have not been scaled, they are ignored.

        Args:
            columns (iterable of str): Column names to unscale.
        Raises:
            KeyError: if any of the column names are not in the dataset.

        """
        self.verify_columns_in_dataset(columns)

        for col in columns:
            scaler, scaled = self.scalers.get(col, (0, 0))
            if not scaled:
                logging.info("column '%s' has not been scaled, ignoring" % col)
                continue

            self.train.loc[:, col] = scaler.inverse_transform(self.train[col])
            self.test.loc[:, col] = scaler.inverse_transform(self.test[col])
            self.scalers[col][1] = False  # mark not scaled

    def unscale_reals(self):
        if self.fguide.real_valueds:
            self.unscale(self.fguide.real_valueds)

    def one_hot_encode(self, columns):
        """One-hot encode the given columns of the train and test data. The
        encoded features are returned as two `scipy.sparse.csr_matrix`
        instances: one for the train set and one for the test set. The indices
        are sorted such that the encoded columns appear in the same relative
        order as in `columns`. A mapping from the column names to the encoded
        features is also returned. The features for columns[i] are present in
        encoded[fmap[i]:fmap[i+1]].

        Returns:
            train_enc (csr_matrix): Sparse matrix with one-hot encoded columns
                from the training dataset.
            test_enc (csr_matrix): Sparse matrix with one-hot encoded columns
                from the testing dataset.
            fmap (list): Map from the column names to the column indices in the
                sparse matrix where the encoded features for that column are
                present.
            encoder (OneHotEncoder): Encoder used to encode the data.
        """
        if not columns:
            return None

        logging.info('one-hot-encoding columns: %s' % ','.join(columns))

        both_sets = pd.concat((self.train[columns], self.test[columns]))
        encoder = preprocessing.OneHotEncoder()
        encoded = encoder.fit_transform(both_sets).sorted_indices()

        # Split apart train and test set arrays after one-hot encoding.
        nd_train = self.train.shape[0]
        train_enc = encoded[:nd_train]
        test_enc = encoded[nd_train:]

        for col in columns:
            logging.debug('unique {}: {}'.format(col, both_sets[col].unique()))

        # Create a feature map for decoding one-hot encoding.
        counts = np.array([both_sets[col].unique().shape[0] for col in columns])
        fmap = []
        for i, column in enumerate(columns):
            unique_elements = np.sort(both_sets[column].unique())
            logging.debug('unique elements for col {}: {}'.format(
                column, unique_elements))
            fmap += ['%s-%d' % (column, idx) for idx in unique_elements]

        logging.info('after one-hot encoding, found # unique values:')
        for attr, n_values in zip(columns, counts):
            logging.info('%s: %d' % (attr, n_values))

        return train_enc, test_enc, fmap, encoder

    def remove_cold_start(self, entities=None):
        """Remove any records from the test set that have entities which do not
        appear in the training set. Optionally pass a list of entities to remove
        cold-start records for.
        """
        entities = self.fguide.entities if entities is None else entities
        for key in entities:
            diff = np.setdiff1d(self.test[key], self.train[key])
            logging.info(
                'removing %d %s ids from the test set.' % (len(diff), key))
            logging.debug(' '.join(map(str, diff)))
            self.test = self.test[~self.test[key].isin(diff)]

    def preprocess(self, impute=True, all_null='raise', normalize=True,
                   use_ents=True, ohc_ents=True, use_cats=True, ohc_cats=True,
                   remove_cold_start=True):
        """Return preprocessed (X, y, eid) pairs for the train and test sets.

        Args:
            impute (bool): Impute missing values for real-valued features.
            all_null (str): See `impute` method.
            normalize (bool): Whether or not real-valued features should be
                normalized. If so, use Z-score scaling to do so. True by
                default.
            use_cats (bool): Whether or not to use categorical features. If False,
                they will not be included in the feature vectors. If True and
                `ohc_cats` is True, they will be included as one-hot-encoded
                features. If True and `ohc_cats` is False, they will be
                included, one per column, without any further preprocessing.
            ohc_cats (bool): Whether or not to one-hot encode categorical
                features. True by default. Ignored if `use_cats` is False.
            use_ents (bool): Whether or not to use entity features. If False,
                they will not be included in the feature vectors. If True and
                `ohc_ents` is True, they will be included as one-hot-encoded
                features. If True and `ohc_ents` is False, they will simply be
                mapped to a 0-contiguous range and included, one per column.
            ohc_ents (bool): Whether or not to one-hot encode entity features.
                True by default. If `use_ents` is False, this will be ignored.
            remove_cold_start {bool | iterable}: If True, remove cold start for
                all entities in the feature guide. If an iterable, remove cold
                start for only the entities in the iterable. Any extraneous
                column names that are not entities will raise a KeyError.

        Preprocessing includes:

        1.  Map all entity IDs to a 0-contiguous range.
        2.  Z-score scale the real-valued features.
        3.  One-hot encode the categorical features (including entity IDs).

        This function tries to be as general as possible to accomodate learning by
        many models. As such, there are a variety of return values (8 in total).
        The first three are for the train set:

        1.  X: feature vector matrix (first categorical, then real-valued)
        2.  y: target values (unchanged from input)
        3.  eids: entity IDs as a numpy ndarray

        The next 3 return values are the same except for the test set. The final
        two values are:

        7.  indices: The indices of each feature in the encoded X matrix.
        8.  nents: The number of unique entities for each entity.

        """
        # might be iterable, in which case any elements would make it true
        if remove_cold_start == True:
            self.remove_cold_start()
        elif remove_cold_start:
            self.remove_cold_start(remove_cold_start)

        train_eids = pd.DataFrame()
        test_eids = pd.DataFrame()
        for entity in self.fguide.entities:
            self.map_column_to_index(entity)
            train_eids[entity] = self.train[entity].values
            test_eids[entity] = self.test[entity].values

        # Z-score scaling of real-valued features.
        self.impute_reals(all_null=all_null)
        if normalize:
            self.scale_reals()
        # TODO: if already normalized, normalize=False will have no effect.

        # One-hot encoding of categorical and possibly entity features.
        to_ohc = OrderedSet()
        if use_ents and ohc_ents:
            to_ohc |= self.fguide.entities
        to_ohc |= self.fguide.categoricals
        # TODO: implement use_cats and ohc_cats args.
        # if use_cats and ohc_cats:
        #     to_ohc |= self.fguide.categoricals

        to_ohc = list(to_ohc)
        if to_ohc:
            train_enc_cats, test_enc_cats, fmap, encoder = self.one_hot_encode(to_ohc)
            n_ohc_total = sum(encoder.n_values_)
            nf_ohc = len(fmap)
        else:
            # TODO: implement use_cats and ohc_cats args.
            n_ohc_total = 0
            nf_ohc = 0
            fmap = []

        # Update feature matrices to include entities if they were not included
        # in the one-hot encoding.
        # Also update the feature map while we're at it.
        n_ents = len(self.fguide.entities)
        if use_ents:
            if ohc_ents:  # already included in feature map
                last_ent = self.fguide.entities[-1]
                pairs = zip(fmap, range(nf_ohc))
                for name, i in pairs[::-1]:
                    if last_ent in name:
                        break

                nf_ents = i + 1  # if 10 active entities, last is at index 9
                n_ents_total = sum(encoder.n_values_[i] for i in range(n_ents))
                n_cats_total = n_ohc_total - n_ents_total
            else:  # need to update feature map
                nf_ents = n_ents
                n_ents_total = n_ents
                n_cats_total = n_ohc_total

                # Add to beginning of feature map.
                labels = list(self.fguide.entities)
                fmap = labels + fmap

                # Add entities onto the beginning of the feature matrices.
                train_enc_cats = sp.sparse.hstack((
                    self.train[labels].values, train_enc_cats))
                test_enc_cats = sp.sparse.hstack((
                    self.test[labels].values, test_enc_cats))
        else:  # not using ents
            nf_ents = 0
            n_ents_total = 0
            n_cats_total = n_ohc_total

        # How many features of each type do we have after one-hot-encoding?
        nf_cats = nf_ohc - nf_ents
        nf_real = len(self.fguide.real_valueds)
        nf = nf_ents + nf_cats + nf_real

        # Add in the real-valued features.
        only_reals = not use_ents and not use_cats
        fmap += self.fguide.real_valueds

        if self.train_reals.shape[1] == 0:
            if only_reals:
                raise ValueError(
                    "no real values and not using ents or cats")
            train_X = train_enc_cats.tocsr()
            test_X = test_enc_cats.tocsr()
        else:
            if only_reals:
                train_X = self.train_reals.values
                test_X = self.test_reals.values
            else:
                train_X = sp.sparse.hstack((
                    train_enc_cats, self.train_reals.values)).tocsr()
                test_X = sp.sparse.hstack((
                    test_enc_cats, self.test_reals.values)).tocsr()

        # Log information regarding encoded features.
        logging.info('number of active entity features: %d of %d' % (
            nf_ents, n_ents_total))
        logging.info('number of active categorical features: %d of %d' % (
            nf_cats, n_cats_total))
        logging.info('number of real-valued features: %d' % nf_real)
        logging.info('Total of %d features after encoding' % nf)

        train_y = np.squeeze(self.train_target.values)
        test_y = np.squeeze(self.test_target.values)

        return (train_X, train_y, train_eids,
                test_X, test_y, test_eids,
                fmap, nf_ents)


# Add properties to PandasTrainTestSplit for quick feature section access.
def _set_prop(dset_name, name, section):
    def get_section(self):
        dset = getattr(self, dset_name)
        names = getattr(self.fguide, section)
        if isinstance(names, basestring):
            return dset[[names]]
        else:
            return dset[list(names)]

    setattr(PandasTrainTestSplit, '%s_%s' % (dset_name, name),
            property(get_section))

for _dset_name in ['train', 'test']:
    for _name, _section in [
            ('reals', 'real_valueds'),
            ('categoricals', 'categoricals'),
            ('entities', 'entities'),
            ('key', 'key'),
            ('target', 'target')]:

        _set_prop(_dset_name, _name, _section)

