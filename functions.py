import numpy as np

## Define functions for multiprocessing
def do_query(idx1d, KD, lon1d, lat1d):
    return KD.query(np.array([lon1d[idx1d], lat1d[idx1d]]).T)
