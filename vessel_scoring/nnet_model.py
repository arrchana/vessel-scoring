# Copyright 2016 SkyTruth
# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
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
# ==============================================================================
#
# Some of this code comes from Google Tensor flow demo:
# https://github.com/tensorflow/tensorflow/blob/r0.9/tensorflow/examples/tutorials/mnist/fully_connected_feed.py

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import tensorflow as tf
from vessel_scoring.utils import get_polynomial_cols
import numpy as np
import time


class NNetModel:
    LEARNING_RATE = 1.0
    MAX_EPOCHS = 20
    HIDDEN = 128
    BATCH_SIZE = 128
    TRAIN_DIR = "."
    DECAY_SCALE = 0.95

    N_WINDOWS = 6
    N_BASE_FEATURES = 3
    N_FEATURES = N_WINDOWS * N_BASE_FEATURES


    windows = ['10800', '1800', '21600', '3600', '43200', '86400']

    def __init__(self, **args):
        """
        windows - list of window sizes to use in features
        See RandomForestClassifier docs for other parameters.
        """
        self.ses = None

    def dump_arg_dict(self):
        raise NotImplementedError()

    def _make_features(self, X):
        x = np.transpose(get_polynomial_cols(X, self.windows))
        return (x.astype('float32') - self.mean) / self.std

    def predict_proba(self, X):
        X = self._make_features(X)
        y = np.zeros([len(X), 2], dtype='float32')
        #
        X1 = self.complete_batch(X)
        ds = self.DataSet(X1,
                        self.complete_batch(y[:,0]), # This is kludgy to pass y in,
                                          # there is likely a way to pass
                                          # in only the feature vector and
                                          # not both
                        self.BATCH_SIZE)
        chunks = []
        steps = len(X1) // self.BATCH_SIZE
        assert len(X1) % self.BATCH_SIZE == 0
        for step in range(steps):
            feed_dict = self.fill_feed_dict(ds)

            chunks.append(self.sess.run(self.predictions, feed_dict=feed_dict))
        ps = np.concatenate(chunks)

        #
        y[:,1] = ps.reshape(-1)[:len(X)]
        y[:,0] = 1 - y[:,1]
        return y

    def fit(self, X, y):
        self.mean = 0
        self.std = 1
        X = self._make_features(X)
        self.mean = X.mean(axis=0, keepdims=True)
        self.std = X.mean(axis=0, keepdims=True)
        X = (X - self.mean) / self.std
        #
        n = len(X)
        n_train = int(self.DECAY_SCALE * n)
        inds = np.arange(n)
        np.random.shuffle(inds)
        #
        train_ds = self.DataSet(X[inds[:n_train]], y[inds[:n_train]], self.BATCH_SIZE)
        eval_ds = self.DataSet(X[inds[n_train:]], y[inds[n_train:]], self.BATCH_SIZE)
        self.run_training(train_ds, eval_ds)

        return self

    def leaky_relu(self, x, alpha=0.01):
        return tf.maximum(alpha*x,x)

    def fill_feed_dict(self, data_set):
      """Fills the feed_dict for training the given step.
      A feed_dict takes the form of:
      feed_dict = {
          <placeholder>: <tensor of values to be passed for placeholder>,
          ....
      }
      Args:
        data_set: The set of features and labels, from input_data.read_data_sets()
      Returns:
        feed_dict: The feed dictionary mapping from placeholders to values.
      """
      # Create the feed_dict for the placeholders filled with the next
      # `batch size ` examples.
      features_feed, labels_feed = data_set.next_batch()
      feed_dict = {
          self.features_placeholder: features_feed,
          self.labels_placeholder: labels_feed,
      }
      return feed_dict


    def do_eval(self, eval_correct, data_set):
      """Runs one evaluation against the full epoch of data.
      Args:
        eval_correct: The Tensor that returns the number of correct predictions.
        data_set: The set of features and labels to evaluate, from
          input_data.read_data_sets().
      """
      # And run one epoch of eval.
      true_count = 0  # Counts the number of correct predictions.
      steps_per_epoch = data_set.num_examples // self.BATCH_SIZE
      num_examples = steps_per_epoch * self.BATCH_SIZE
      for step in range(steps_per_epoch):
        feed_dict = self.fill_feed_dict(data_set)
        true_count += self.sess.run(eval_correct, feed_dict=feed_dict)
      precision = true_count / num_examples
      print('  Num examples: %d  Num correct: %d  Precision @ 1: %0.04f' %
            (num_examples, true_count, precision))

    def inference(self, features, hidden_units):
        """Build the model up to where it may be used for inference.
        Args:
        features: features placeholder, from inputs().
        hidden_units: Size of the hidden layers.
    #     maxout_pooling: Degree of maxout to use
        Returns:
        softmax_linear: Output tensor with the computed logits.
        """


        # Hidden 1
        with tf.name_scope('hidden1'):
            weights = tf.Variable(
                tf.truncated_normal([self.N_FEATURES, hidden_units],
                                    stddev=1.0 / np.sqrt(self.N_FEATURES)),
                name='weights')
            biases = tf.Variable(tf.zeros([hidden_units]),
                                 name='biases')
            hidden1 = self.leaky_relu(tf.matmul(features, weights) + biases)
        # Dropout 1
        dropout1 = tf.nn.dropout(hidden1, 0.5)
        # Hidden 2
        with tf.name_scope('hidden2'):
            weights = tf.Variable(
                tf.truncated_normal([hidden_units, hidden_units],
                                    stddev=1.0 / np.sqrt(hidden_units)),
                name='weights')
            biases = tf.Variable(tf.zeros([hidden_units]),
                                 name='biases')
            hidden2 = self.leaky_relu((tf.matmul(dropout1, weights) + biases))
        # Dropout2
        dropout2 = tf.nn.dropout(hidden2, 0.5)
        # Linear
        with tf.name_scope('logit'):
            weights = tf.Variable(
                tf.truncated_normal([hidden_units, 1],
                                    stddev=1.0 / np.sqrt(hidden_units)),
                name='weights')
            biases = tf.Variable(tf.zeros([1]),
                                 name='biases')
            logits = tf.reshape(tf.matmul(dropout2, weights) + biases, (-1,))
        return logits



    def lossfunc(self, logits, labels):
      """Calculates the loss from the logits and the labels.
      Args:
        logits: Logits tensor, float - [BATCH_SIZE, NUM_CLASSES].
        labels: Labels tensor, int32 - [BATCH_SIZE].
      Returns:
        loss: Loss tensor of type float.
      """
      cross_entropy = tf.nn.sigmoid_cross_entropy_with_logits(
          logits, labels, name='xentropy')
      loss = tf.reduce_mean(cross_entropy, name='xentropy_mean')
      return loss


    def training(self, loss, learning_rate):
      """Sets up the training Ops.
      Creates a summarizer to track the loss over time in TensorBoard.
      Creates an optimizer and applies the gradients to all trainable variables.
      The Op returned by this function is what must be passed to the
      `self.sess.run()` call to cause the model to train.
      Args:
        loss: Loss tensor, from loss().
        learning_rate: The learning rate to use for gradient descent.
      Returns:
        train_op: The Op for training.
      """
      # Add a scalar summary for the snapshot loss.
      tf.scalar_summary(loss.op.name, loss)
      # Create the gradient descent optimizer with the given learning rate.
      optimizer = tf.train.GradientDescentOptimizer(learning_rate)
      # Create a variable to track the global step.
      global_step = tf.Variable(0, name='global_step', trainable=False)
      # Use the optimizer to apply the gradients that minimize the loss
      # (and also increment the global step counter) as a single training step.
      train_op = optimizer.minimize(loss, global_step=global_step)
      return train_op


    def evaluation(self, logits, labels):
      """Evaluate the quality of the logits at predicting the label.
      Args:
        logits: Logits tensor, float - [BATCH_SIZE].
        labels: Labels tensor, float - [BATCH_SIZE]
      Returns:
        A scalar int32 tensor with the number of examples (out of BATCH_SIZE)
        that were predicted correctly.
      """
      # For a classifier model, we can use the in_top_k Op.
      # It returns a bool tensor with shape [BATCH_SIZE] that is true for
      # the examples where the label is in the top k (here k=1)
      # of all logits for that example.
      correct = tf.equal(tf.round(tf.sigmoid(logits)), labels)
      # Return the number of true entries.
      return tf.reduce_sum(tf.cast(correct, tf.int32))



    class DataSet(object):

        def __init__(self,
                     features,
                     labels,
                     BATCH_SIZE):
            """Construct a DataSet.
            """
            dtype = 'float32'

            assert features.shape[0] == labels.shape[0], (
              'features.shape: %s labels.shape: %s' % (features.shape, labels.shape))
            self._num_examples = features.shape[0]
            self._features = features
            self._labels = labels
            self._epochs_completed = 0
            self._index_in_epoch = 0
            self.BATCH_SIZE = BATCH_SIZE

        @property
        def features(self):
            return self._features

        @property
        def labels(self):
            return self._labels

        @property
        def num_examples(self):
            return self._num_examples

        @property
        def epochs_completed(self):
            return self._epochs_completed

        def next_batch(self, fake_data=False):
            """Return the next `BATCH_SIZE` examples from this data set."""
            start = self._index_in_epoch
            self._index_in_epoch += self.BATCH_SIZE
            if self._index_in_epoch > self._num_examples:
              # Finished epoch
              self._epochs_completed += 1
              # Shuffle the data
              perm = np.arange(self._num_examples)
              np.random.shuffle(perm)
              self._features = self._features[perm]
              self._labels = self._labels[perm]
              # Start next epoch
              start = 0
              self._index_in_epoch = self.BATCH_SIZE
              assert self.BATCH_SIZE <= self._num_examples
            end = self._index_in_epoch
            return self._features[start:end], self._labels[start:end]



    def run_training(self, train_ds, eval_ds):
      """Train for a number of steps."""
      # Get the sets of features and labels for training, validation, and
      # test on .
    #   data_sets = input_data.read_data_sets(FLAGS.train_dir, FLAGS.fake_data)




      # Tell TensorFlow that the model will be built into the default Graph.
      with tf.Graph().as_default():
        # Note that the shapes of the placeholders match the shapes of the full
        # image and label tensors, except the first dimension is now BATCH_SIZE
        self.features_placeholder = tf.placeholder(tf.float32, shape=(self.BATCH_SIZE, self.N_FEATURES))
        self.labels_placeholder = tf.placeholder(tf.float32, shape=(self.BATCH_SIZE))

        # Build a Graph that computes self.predictions from the inference model.
        self.logits = self.inference(self.features_placeholder, self.HIDDEN)

        # Build a final output prediction
        self.predictions = tf.nn.sigmoid(self.logits)

        # Add to the Graph the Ops for loss calculation.
        loss = self.lossfunc(self.logits, self.labels_placeholder)

        # Add to the Graph the Ops that calculate and apply gradients.
        learning_rate = tf.Variable(self.LEARNING_RATE, name="learning_rate")
        #
        train_op = self.training(loss, learning_rate)

        # Add the Op to compare the self.logits to the labels during evaluation.
        eval_correct = self.evaluation(self.logits, self.labels_placeholder)

        # Build the summary operation based on the TF collection of Summaries.
        summary_op = tf.merge_all_summaries()

        # Add the variable initializer Op.
        init = tf.initialize_all_variables()

        # Create a saver for writing training checkpoints.
        saver = tf.train.Saver()

        # Create a session for running Ops on the Graph.
        self.sess = tf.Session()

        # Instantiate a SummaryWriter to output summaries and the Graph.
        summary_writer = tf.train.SummaryWriter(self.TRAIN_DIR, self.sess.graph)

        # And then after everything is built:

        # Run the Op to initialize the variables.
        self.sess.run(init)

        # Start the training loop.
        epoch = 0
        last_epoch = 0
        step = 0
        while epoch < self.MAX_EPOCHS:
          try:
              start_time = time.time()

              # Fill a feed dictionary with the actual set of features and labels
              # for this particular training step.
              feed_dict = self.fill_feed_dict(train_ds)

              # Run one step of the model.  The return values are the activations
              # from the `train_op` (which is discarded) and the `loss` Op.  To
              # inspect the values of your Ops or variables, you may include them
              # in the list passed to self.sess.run() and the value tensors will be
              # returned in the tuple from the call.
              _, loss_value = self.sess.run([train_op, loss],
                                       feed_dict=feed_dict)

              duration = time.time() - start_time

              # Write the summaries and print an overview fairly often.
              if step % 100 == 0:
                # Print status to stdout.
                print('Step %d: loss = %.2f (%.3f sec)' % (step, loss_value, duration))
                # Update the events file.
                summary_str = self.sess.run(summary_op, feed_dict=feed_dict)
                summary_writer.add_summary(summary_str, step)
                summary_writer.flush()


              epoch = (step * self.BATCH_SIZE) // train_ds.num_examples
              if epoch != last_epoch or epoch >= self.MAX_EPOCHS:
                learning_rate.assign(0.95 * learning_rate)
                # Save a checkpoint and evaluate the model .
                saver.save(self.sess, self.TRAIN_DIR, global_step=step)
                # Evaluate against the training set.
                print("Epoch:", epoch)
                print('Training Data Eval:')
                self.do_eval(eval_correct,
                             train_ds)
                # Evaluate against the validation set.
                print('Validation Data Eval:')
                self.do_eval(eval_correct,
                             eval_ds)
              last_epoch = epoch
              step += 1
          except:
              break


    def complete_batch(self, x):
        n = len(x)
        assert n > self.BATCH_SIZE // 2 # This limitation can be fixed
        if n % self.BATCH_SIZE == 0:
            return x
        else:
            while len(x) < self.BATCH_SIZE // 2:
                x = np.concatenate([x, x], axis=0)
            extra = self.BATCH_SIZE - n % self.BATCH_SIZE
            return np.concatenate([x, x[:extra]], axis=0)