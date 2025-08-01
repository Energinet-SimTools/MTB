from tsdownsample import MinMaxLTTBDownsampler
from down_sampling_method import DownSamplingMethod
from typing import List, Tuple
import numpy as np
import pandas as pd


def calculate_gradient(time, values):
    dt = np.gradient(time)
    dy = np.gradient(values)
    gradient = dy / dt
    return gradient


def downSample(x_value, y_value, downsampling_method, gradient_threshold):
    if downsampling_method == DownSamplingMethod.GRADIENT:
        x_value, y_value = downsample_based_on_gradient(x_value, y_value, gradient_threshold)
    elif downsampling_method == DownSamplingMethod.AMOUNT:
        x_value, y_value = down_sample(x_value, y_value)
    return x_value, y_value
        
def downsample_based_on_gradient(time, values, gradient_threshold):
    values = pd.to_numeric(values, errors='coerce')
    gradient = calculate_gradient(time, values)
    low_gradient_indices = np.where(np.abs(gradient) < gradient_threshold)[0]

    # Select points where the gradient is low (downsampled points)
    downsampled_indices = low_gradient_indices[::20]  # Change 10 to control the downsampling rate

    # Combine low gradient downsampled points with high gradient points
    high_gradient_indices = np.where(np.abs(gradient) >= gradient_threshold)[0]
    combined_indices = np.unique(np.concatenate([downsampled_indices, high_gradient_indices]))

    downsampled_time = time[combined_indices]
    downsampled_values = values[combined_indices]

    return downsampled_time, downsampled_values


def down_sample(data_x_axis: List[int], data_y_axis: List[int]) -> Tuple[List[int], List[int]]:
    if len(data_x_axis) < 100:
        return data_x_axis, data_y_axis
    downsample = MinMaxLTTBDownsampler().downsample(data_x_axis, data_y_axis, n_out=100)
    return data_x_axis[downsample], data_y_axis[downsample]


#def get_down_sampling_method(fSetup: Dict[str, str]):
#    if 'down_sampling_method' in fSetup:
#        return DownSamplingMethod.from_string(str(fSetup['down_sampling_method']))
#    else:
#        return DownSamplingMethod.NO_DOWN_SAMPLING