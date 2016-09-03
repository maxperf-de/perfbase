# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_access - Support functions for cached line-by-line access of input files
#
#     This file is part of perfbase.
#
#     perfbase is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 2 of the License, or
#     (at your option) any later version.
#
#     perfbase is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with perfbase; if not, write to the Free Software
#     Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os

#
# parameters for operation
#
# For each file, we keep the current and the previous block in memory.
# No control of total cache size yet.
block_sz = 10*1024*1024   # size of a cache-block (in bytes).

#
# variables for operation
#
open_fds = {}  # maps filename to file descriptor
prev_buf = {}  # maps filename to "previous" buffer
prev_idx = {}  # maps filename to index of first line in "previous" buffer
curr_buf = {}  # maps filename to "current" buffer
curr_idx = {}  # maps filename to index of first line in "current" buffer


def flushlines(fname):
    if fname in prev_buf:
        del prev_buf[fname]
    if fname in curr_buf:
        del curr_buf[fname]

    prev_buf[fname] = []
    prev_idx[fname] = 0
    curr_buf[fname] = []
    curr_idx[fname] = 0
    return


def rdline(fname, idx):
    if fname not in open_fds:
        open_fds[fname] = open(fname, 'r')
        flushlines(fname)

    # need to adapt the index from starting at 1 (pb_input) to 0 (here)
    idx -= 1

    if idx < prev_idx[fname]:
        # For now, we just clear the cache and read again from the start
        print "#* WARNING: had to flush line cache for file %s" % (fname)
        open_fds[fname].seek(0)
        flushlines(fname)
        
    while idx >= curr_idx[fname] + len(curr_buf[fname]):
        # need to read new data, current buffer becomes previous buffer
        del prev_buf[fname]
        prev_buf[fname] = curr_buf[fname]
        prev_idx[fname] = curr_idx[fname]
        
        curr_idx[fname] += len(curr_buf[fname])
        del curr_buf[fname]
        curr_buf[fname] = open_fds[fname].readlines(block_sz)
        if len(curr_buf[fname]) == 0:
            # EOF - return empty string
            return ''

    c_i = curr_idx[fname]
    if idx >= c_i and idx < c_i + len(curr_buf[fname]):
        return curr_buf[fname][idx - c_i]

    p_i = prev_idx[fname]
    if idx >= p_i and idx < p_i + len(prev_buf[fname]):
        return prev_buf[fname][idx - p_i]

    raise IndexError, "line %d to be accesses to too far ahead" % idx
    return

