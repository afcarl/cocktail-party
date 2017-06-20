import argparse
import os
import glob
import random
import shutil
import math
import multiprocessing
from datetime import datetime

from keras.layers import Dense, Convolution2D, MaxPooling2D, BatchNormalization, Activation, Dropout, LeakyReLU, Flatten
from keras.models import Sequential, model_from_json
from keras import optimizers

import numpy as np
import h5py
import cv2

from mediaio.video_io import VideoFileReader
from mediaio.audio_io import AudioSignal
from dsp.spectogram import MelConverter


class VisualSpeechPredictor:

	def __init__(self):
		pass

	@staticmethod
	def load(model_cache_path, weights_cache_path):
		predictor = VisualSpeechPredictor()

		with open(model_cache_path, "r") as model_fd:
			predictor._model = model_from_json(model_fd.read())

		predictor._model.load_weights(weights_cache_path)

		return predictor

	def init_model(self, video_shape, audio_spectogram_size):
		self._model = Sequential()

		self._model.add(Convolution2D(32, (3, 3), padding="same", kernel_initializer="he_normal", input_shape=video_shape))
		self._model.add(BatchNormalization())
		self._model.add(LeakyReLU())
		# self._model.add(MaxPooling2D(pool_size=(2, 2)))

		# self._model.add(Convolution2D(32, (3, 3), padding="same", kernel_initializer="he_normal"))
		# self._model.add(BatchNormalization())
		# self._model.add(LeakyReLU())

		self._model.add(Convolution2D(32, (3, 3), padding="same", kernel_initializer="he_normal"))
		self._model.add(BatchNormalization())
		self._model.add(LeakyReLU())
		self._model.add(MaxPooling2D(pool_size=(2, 2)))
		self._model.add(Dropout(0.2))

		self._model.add(Convolution2D(64, (3, 3), padding="same", kernel_initializer="he_normal"))
		self._model.add(BatchNormalization())
		self._model.add(LeakyReLU())

		self._model.add(Convolution2D(64, (3, 3), padding="same", kernel_initializer="he_normal"))
		self._model.add(BatchNormalization())
		self._model.add(LeakyReLU())
		self._model.add(MaxPooling2D(pool_size=(2, 2)))
		self._model.add(Dropout(0.2))

		self._model.add(Convolution2D(128, (3, 3), padding="same", kernel_initializer="he_normal"))
		self._model.add(BatchNormalization())
		self._model.add(LeakyReLU())

		self._model.add(Convolution2D(128, (3, 3), padding="same", kernel_initializer="he_normal"))
		self._model.add(BatchNormalization())
		self._model.add(LeakyReLU())
		self._model.add(MaxPooling2D(pool_size=(2, 2)))
		self._model.add(Dropout(0.2))

		# self._model.add(Convolution2D(128, (3, 3), padding="same", kernel_initializer="he_normal"))
		# self._model.add(BatchNormalization())
		# self._model.add(LeakyReLU())
		#
		# self._model.add(Convolution2D(128, (3, 3), padding="same", kernel_initializer="he_normal"))
		# self._model.add(BatchNormalization())
		# self._model.add(Activation("tanh"))
		# self._model.add(MaxPooling2D(pool_size=(2, 2)))
		# self._model.add(Dropout(0.2))

		self._model.add(Flatten())

		self._model.add(Dense(units=512))
		self._model.add(BatchNormalization())
		self._model.add(Activation("relu"))
		self._model.add(Dropout(0.2))

		self._model.add(Dense(units=512))
		self._model.add(BatchNormalization())
		self._model.add(Activation("relu"))
		self._model.add(Dropout(0.2))

		self._model.add(Dense(units=audio_spectogram_size))

		optimizer = optimizers.adam(lr=0.01, decay=1e-6)
		self._model.compile(loss='mean_squared_error', optimizer=optimizer)

	def train(self, x, y):
		self._model.fit(x, y, batch_size=32, epochs=100, verbose=1)

	def evaluate(self, x, y):
		score = self._model.evaluate(x, y, verbose=1)
		return score

	def predict(self, x):
		y = self._model.predict(x)
		return y

	def dump(self, model_cache_path, weights_cache_path):
		with open(model_cache_path, "w") as model_fd:
			model_fd.write(self._model.to_json())

		self._model.save_weights(weights_cache_path)


def preprocess_video_sample(video_file_path, slice_duration_ms=330):
	face_detector = cv2.CascadeClassifier(
		os.path.join(os.path.dirname(__file__), "res", "haarcascade_frontalface_alt.xml")
	)

	with VideoFileReader(video_file_path) as reader:
		frames = reader.read_all_frames(convert_to_gray_scale=True)
		frames_per_slice = (float(slice_duration_ms) / 1000) * reader.get_frame_rate()
		n_slices = int(float(reader.get_frame_count()) / frames_per_slice)

	face_cropped_frames = np.zeros(shape=(75, 128, 128), dtype=np.float32)
	for i in range(frames.shape[0]):
		faces = face_detector.detectMultiScale(frames[i, :], minSize=(200, 200), maxSize=(400, 400))
		if len(faces) == 1:
			(face_x, face_y, face_width, face_height) = faces[0]
			face = frames[i, face_y: (face_y + face_height), face_x: (face_x + face_width)]

			face_cropped_frames[i, :] = cv2.resize(face, (128, 128))

		else:
			print("failed to locate face in %s" % video_file_path)
			return None

	# fit to tensorflow channel_last data format
	face_cropped_frames = face_cropped_frames.transpose((1, 2, 0))

	face_cropped_frames /= 255
	face_cropped_frames -= np.mean(face_cropped_frames)

	slices = [
		face_cropped_frames[:, :, int(i * frames_per_slice) : int(math.ceil((i + 1) * frames_per_slice))]
		for i in range(n_slices)
	]

	return np.stack(slices)


def preprocess_audio_sample(audio_file_path, slice_duration_ms=330):
	audio_signal = AudioSignal.from_wav_file(audio_file_path)

	new_signal_length = int(math.ceil(
		float(audio_signal.get_number_of_samples()) / MelConverter.HOP_LENGTH
	)) * MelConverter.HOP_LENGTH

	audio_signal.pad_with_zeros(new_signal_length)

	mel_converter = MelConverter(audio_signal.get_sample_rate())
	mel_spectogram = mel_converter.signal_to_mel_spectogram(audio_signal)

	samples_per_slice = int((float(slice_duration_ms) / 1000) * audio_signal.get_sample_rate())
	spectogram_samples_per_slice = int(samples_per_slice / MelConverter.HOP_LENGTH)

	n_slices = int(mel_spectogram.shape[1] / spectogram_samples_per_slice)

	sample = np.ndarray(shape=(n_slices, MelConverter.N_MEL_FREQS * spectogram_samples_per_slice))

	for i in range(n_slices):
		sample[i, :] = mel_spectogram[:, (i * spectogram_samples_per_slice):((i + 1) * spectogram_samples_per_slice)].flatten()

	return sample


def reconstruct_audio_signal(y, sample_rate):
	slice_mel_spectograms = [y[i, :].reshape((MelConverter.N_MEL_FREQS, -1)) for i in range(y.shape[0])]
	full_mel_spectogram = np.concatenate(slice_mel_spectograms, axis=1)

	mel_converter = MelConverter(sample_rate)
	return mel_converter.reconstruct_signal_from_mel_spectogram(full_mel_spectogram)


def video_to_audio_path(video_file_path):
	return video_file_path.replace("video", "audio").replace(".mpg", ".wav")


def preprocess_data(video_file_paths):
	print("reading dataset...")

	audio_file_paths = [video_to_audio_path(f) for f in video_file_paths]

	thread_pool = multiprocessing.Pool(8)
	x = thread_pool.map(preprocess_video_sample, video_file_paths)
	y = thread_pool.map(preprocess_audio_sample, audio_file_paths)

	invalid_sample_ids = [i for i, sample in enumerate(x) if sample is None]
	x = [sample for i, sample in enumerate(x) if i not in invalid_sample_ids]
	y = [sample for i, sample in enumerate(y) if i not in invalid_sample_ids]

	return np.concatenate(x), np.concatenate(y)


def list_video_files(dataset_dir, speaker_ids=None, max_files=None):
	video_file_paths = []

	if speaker_ids is None:
		speaker_ids = os.listdir(dataset_dir)

	for speaker_id in speaker_ids:
		video_file_paths.extend(glob.glob(os.path.join(dataset_dir, speaker_id, "video", "*.mpg")))

	random.shuffle(video_file_paths)
	return video_file_paths[:max_files]


def train(args):
	video_file_paths = list_video_files(args.dataset_dir, args.speakers, max_files=1000)
	x, y = preprocess_data(video_file_paths)

	predictor = VisualSpeechPredictor()
	predictor.init_model(video_shape=x.shape[1:], audio_spectogram_size=y.shape[1])
	predictor.train(x, y)
	predictor.dump(args.model_cache, args.weights_cache)


def predict(args):
	predictor = VisualSpeechPredictor.load(args.model_cache, args.weights_cache)

	prediction_output_dir = os.path.join(args.prediction_output_dir, '{:%Y-%m-%d_%H-%M-%S}'.format(datetime.now()))
	os.mkdir(prediction_output_dir)

	video_file_paths = list_video_files(args.dataset_dir, args.speakers, max_files=10)
	for video_file_path in video_file_paths:
		x = preprocess_video_sample(video_file_path)
		if x is None:
			print("invalid sample (%s). skipping" % video_file_path)
			continue

		y_predicted = predictor.predict(x)

		sample_name = os.path.splitext(os.path.basename(video_file_path))[0]

		reconstructed_signal = reconstruct_audio_signal(y_predicted, sample_rate=44100)
		reconstructed_signal.save_to_wav_file(os.path.join(prediction_output_dir, "%s.wav" % sample_name))

		shutil.copy(video_file_path, prediction_output_dir)


def main():
	parser = argparse.ArgumentParser(add_help=False)
	action_parsers = parser.add_subparsers()

	train_parser = action_parsers.add_parser("train")
	train_parser.add_argument("dataset_dir", type=str)
	train_parser.add_argument("model_cache", type=str)
	train_parser.add_argument("weights_cache", type=str)
	train_parser.add_argument("--speakers", nargs="+", type=str)
	train_parser.set_defaults(func=train)

	predict_parser = action_parsers.add_parser("predict")
	predict_parser.add_argument("dataset_dir", type=str)
	predict_parser.add_argument("model_cache", type=str)
	predict_parser.add_argument("weights_cache", type=str)
	predict_parser.add_argument("prediction_output_dir", type=str)
	predict_parser.add_argument("--speakers", nargs="+", type=str)
	predict_parser.set_defaults(func=predict)

	args = parser.parse_args()
	args.func(args)

if __name__ == "__main__":
	main()