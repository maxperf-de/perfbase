# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#            (c) 2009-2010 IAT GmbH
#            Joachim Worringen <joachim.worringen@iathh.de>
#
# pb_plotutil - Provide classes to plot data with different backends
#               (like gnuplot, xmgrace, OpenDX, ...)
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

from pb_common import *

from os import popen
from string import rstrip, split
from sys import stdin, stdout, exit, platform



class plot:
    def __init__(self, title=None, options=None, color=True):
        return None
    def set_data(self, data, index=None, title=None, label=None, plottype="graphs", plotstyle=None, options=None):
        """Provide the data to be plotted. This function can be called multiply
        to have multiple data sets be plotted into a single plot. In this case,
        it has to be considered

        'data' is a n-dimensional array of data (lists of lists), matching the 'type' of
        the plot as specified on initialization.

        'title' is the title of this data set to be shown in the plot.

        'label' needs to be a dictionary indexed by 'x', 'y' and/or 'z'. Each key may
        return a string which will be used as a label for the respective axis.

        'index' needs to be dictionary indexed by 'x', 'y' and/or 'z'. Each key may return
        a list of index values to be used for this dimension; if not provided, the natural
        index will be used (0, 1, 2, ..).

        'type' is the same sort of argument as in __init__() and can be used to override the
        default set there. 
        """
        
        return
    def clear_data(self):
        """Remove all data sets."""
        return
    def plot(self, target="screen", prefix=None):
        """Actually create the plot.

        'target' indicates where to create the plot, which means the screen
        or a file with a specific format.

        'prefix' is required if a file-based target is used and represents the
        base file name. A target-specific suffix is appended."""
        return
    def save(self, target="pdf", prefix=None):
        """Save the commands and the data to files for offline-plotting.

        'prefix' is the base filename to be used; suffixes will be added as
        required."""
        return
    def close(self):
        return


class axis_properties:
    pass


class gnuplot(plot):
    def __init__(self, title=None, options=None, color=True):
        self.gnuplot = None

        if platform == 'win32':
            self.gnuplot_cmd = "pgnuplot"
            self.screen_term = "windows"
        else:
            self.gnuplot_cmd = "gnuplot -persist"
            self.screen_term = "x11 enhanced"            

        fontsize2points = { 'tiny':8, 'small':10, 'normal':12, 'large':14, 'huge':16 }
        elmtsize2points = { 'tiny':0, 'small':1, 'normal':2, 'large':3, 'huge':4 }
        self.fontsize = fontsize2points['normal']
        self.elmtsize = elmtsize2points['normal']

        self.gp_opts = ""
        self.plot_cmd = "plot"
        self.ndims = 2
        self.ntics = -1   # automatic
        self.set_opts = []
        self.use_color = color
        self.logscale = {}
        if options != None:
            for o in options:
                splt_o = o.split()
                # a gnuplot startup option has the format "-opt"
                if splt_o[0][0] == "-":
                    if platform == 'win32' and splt_o[0] == "-persist":
                        # -persist is not supported under windows
                        continue
                    self.gp_opts += " %s " % splt_o[0]
                    continue
                elif splt_o[0] == "ndims":
                    if splt_o[1] == "3":
                        self.plot_cmd = "splot"
                    self.ndims = int(splt_o[1])
                    continue
                elif splt_o[0] == "logscale":
                    dim = splt_o[1]
                    place = ''
                    if len(dim) == 2 and dim[1] == '2':
                        place = '2'
                    self.logscale[(dim,place)] = int(splt_o[2])
                elif splt_o[0] == "fontsize":
                    self.fontsize = fontsize2points[splt_o[1]]
                elif splt_o[0] == "elements":
                    self.elmtsize = elmtsize2points[splt_o[1]]
                elif splt_o[0] == "ntics":
                    self.ntics = int(splt_o[1])
                else:
                    self.set_opts.append(o)
                    
        self.title = title
        self.data_sets = []
        self.data_titles = []
        self.plot_types = []
        self.plot_styles = []
        self.n_dims = 0
        self.index = {}
        self.label = {}
        self.axis = {}
        self.axis_cnt = {}     # how many axes are used in this dimension?
        self.axis_place = {}   # map tuple (dataset_idx, dimension) to the place of the related axis
        for dim in ['x', 'y', 'z']:
            self.axis_cnt[dim] = 1
            for place in ['', '2']:
                axis_idx = (dim,place)
                self.axis[axis_idx] = axis_properties()
                self.axis[axis_idx].set = False
                self.axis[axis_idx].in_use = False
            
        return

    def set_data(self, data, index=None, title="", label=None, plottype="graphs", plotstyle=None, options={}):
        # Check for correct number of dimensions.
        if not self.n_dims:
            self.n_dims = len(data) + 1
        else:
            if self.n_dims != len(data) + 1:
                raise DataError, "mismatch of number of dimensions (is %d, should be %d)" % \
                      (len(data) + 1, self.ndims)

        # Check for matching number of data points in each dimensional extent.
        if len(self.data_sets) != 0:            
            for d in range(self.n_dims - 1):
                if len(self.data_sets[0][d]) != len(data[d]) and be_verbose():
                    print "#* WARNING (output '%s'): mismatch of extent of dimension %d" % \
                          (self.title, d)
                    print "   (old: %d, new: %d)" % (len(data[d]), len(self.data_sets[0][d]))

        self.data_titles.append(title)
        dset_idx = len(self.data_sets)
        self.data_sets.append(data)
        self.plot_types.append(plottype)
        self.plot_styles.append(plotstyle)

        axis_defaults = { 'x':'bottom', 'y':'left', 'z':'left' }
        for dim in ['x', 'y', 'z']:
            place = ''
            k = dim+'-axis'
            if options.has_key(k):
                if options[k] != axis_defaults[dim]:
                    place = '2'
                    self.axis_cnt[dim] += 1
            axis_idx = (dim, place)
            self.axis_place[(dset_idx, dim)] = place

            if index.has_key(dim):
                # The index can either be a tuple or a list. For a tuple 'idx', idx[0] is
                # the minimum value, idx[1] is the maximum value, and idx[2] (optional) is the
                # increment.
                # If the index is given as a list, it may consist of numeric or string values
                # which are interpreted as literal ticks. For numeric values, the indexes of
                # different datasets may be different and are joined within this function.
                # String index lists need to be identical across all datasets.
                if isinstance(index[dim], tuple):
                    if len(index[dim]) == 2 or len(index[dim]) == 3:
                        idx_list = []
                        min = index[dim][0]
                        max = index[dim][1]
                        if len(index[dim]) == 3:
                            # For int types, we could use range(), but we need to support float
                            i = min
                            while i < max:
                                # What about descending lists?
                                idx_list.append(i)
                                i += index[dim][2]
                    else:
                        raise SpecificationError, "index tuple must be of length 2 or 3"
                else:
                    idx_list = index[dim]
                    
                if self.axis[axis_idx].set:
                    # A previous dataset has already supplied index information; check if
                    # this can be used together with the new information here.
                    if self.axis[axis_idx].idx_list != None:
                        # XXX It is probably not necessary to abort here - using the existing
                        # tics should be okay! Disable this test for now. We need a a better test
                        # to see if and how different idx lists can be merged.
                        if False and isinstance(self.axis[axis_idx].idx_list[0], str):
                            if self.axis[axis_idx].idx_list != idx_list:
                                raise SpecificationError, "index lists for %s-axis (%s) do not match" % (dim, place)
                        else:
                            # Match numerical lists. Gnuplot will ignore duplicate entries. But
                            # take care that we do not specify too many indexes.
                            for tic in idx_list:
                                if len(self.axis[axis_idx].idx_list) > pb_max_idx_cnt:
                                    break
                                if tic not in self.axis[axis_idx].idx_list:
                                    self.axis[axis_idx].idx_list.append(tic)
                    else:
                        if self.axis[axis_idx].min > min:
                            self.axis[axis_idx].min = min
                        if self.axis[axis_idx].max < max:
                            self.axis[axis_idx].max = max
                else:
                    # Initialize the appearance of this axis
                    if len(idx_list) > 0:
                        self.axis[axis_idx].set = True
                        self.axis[axis_idx].idx_list = idx_list
                        self.axis[axis_idx].min = None
                        self.axis[axis_idx].max = None
                    else:
                        self.axis[axis_idx].idx_list = None
                        #self.axis[axis_idx].min = min
                        #self.axis[axis_idx].max = max
                    self.axis[axis_idx].in_use = True
            if label.has_key(dim):
                if self.label.has_key(axis_idx):
                    if self.label[axis_idx] != label[dim] and be_verbose():
                        print "#* WARNING (output '%s'): %s-axis labels do not match ('%s' vs. '%s')" \
                              % (self.title, dim, self.label[axis_idx], label[dim])
                        print "   Using label '%s' of first data set." % self.label[axis_idx]
                else:
                    self.label[axis_idx] = label[dim]
        
        return

    def clear_data(self):
        self.data_sets = []
        self.data_titles = []
        self.n_dims = 0
        self.index = {}
        self.label = {}
        return

    def _clean_str(self, title):
        """Remove everything that gnuplot does not like in a string."""
        rval = ""
        sub_titles = title.split("'")
        for s in sub_titles:
            rval += s
        return rval
    
    def _setup_cmds_bars(self):
        X = 0
        cmd_strs = []
        n_sets = len(self.data_sets)
        self.bar_scale_factor = 0.8
        
        cmd_strs.append("set boxwidth %f\n" % (self.bar_scale_factor/n_sets))
        cmd_strs.append("set style fill solid 1.0\n")
        cmd_strs.append("set style line 1 lt 0\n")

        place_to_dsetidx = {}
        for dset_idx in range(n_sets):
            p = self.axis_place[(dset_idx, 'x')]
            if not place_to_dsetidx.has_key(p):
                place_to_dsetidx[p] = dset_idx

        for k,v in place_to_dsetidx.iteritems():
            # Here, we need to look at all x-values from all datasets shown on *this* axis
            # to construct a correct x-axis description.
            ap = self.axis_place[(v, 'x')]
            x_vals = []
            for dset_idx in range(n_sets):
                if self.axis_place[(dset_idx, 'x')] != ap:
                    # not the same axis
                    continue
                for x_val in self.data_sets[dset_idx][X]:
                    if x_val is not None and x_val not in x_vals:
                        x_vals.append(x_val)
            # don't sort as the data behind the x_vals is not sorted with the index!
            #x_vals.sort()
            n_elmts = len(x_vals)
            
            cmd_strs.append("set x%szeroaxis\n" % k)
            cmd_strs.append("set x%srange[-0.5:%f]\n" % (k, float(n_elmts)-0.5))

            tic_cmd = "set x%stics (" % k
            # The tics are created by looking at the first dataset for this axisonly.
            # If multiple datasets are provided for the same axis, they need to have the same x-values!
            if self.ntics < 0:
                idx_inc = 1
            elif self.ntics == 0:
                idx_inc = 0
            else:
                idx_inc = len(x_vals)/int(self.ntics)
            if idx_inc > 0:
                for x_idx in range(0, len(x_vals), idx_inc):
                    tic_cmd += '"%s" %d,' % (build_pow2_label(x_vals[x_idx]), x_idx)
                tic_cmd = tic_cmd[:-1] + ')\n'
                cmd_strs.append(tic_cmd)

        return cmd_strs

    def _build_axis_str(self, dset_idx, dims=('x', 'y')):
        # The axes keyword does onyl work for 2D plots
        axes = ""
        if self.ndims == 2:
            axes = "axes "
            for d in dims:                
                p = self.axis_place[(dset_idx, d)]
                if p == '':
                    p = '1'
                axes += d+p

        return axes

    def _plot_bars(self):
        """A barchart does not plot the values in the numerical scaling,
        but instead one equi-distant next to the other, with the label
        giving the actual numerical value."""
        X = 0
        Y = 1
        
        cmd_strs = []
        data_pts = []
        n_sets = len(self.data_sets)
        x_pos_off = self.bar_scale_factor*(n_sets-1)/(n_sets*2)
        x_pos_inc = self.bar_scale_factor/n_sets
        
        plot_cmdline = "%s " % self.plot_cmd
        for dset in range(len(self.data_sets)):
            data_title = self._clean_str(self.data_titles[dset])
            plot_cmdline += "'-' %s title '%s' %s with %s," % \
                        (mk_using_str(len(self.data_sets[dset])),
                         mk_enhanced_gp(data_title),
                         self._build_axis_str(dset),
                         self.plot_styles[dset])
        plot_cmdline = plot_cmdline[:-1] + "\n"
        cmd_strs.append(plot_cmdline)

        # Create index (x-values), data (y-values) tuples.
        # We need to take care that we don't mess up the data if we plot
        # multiple data sets into one chart: we can not assume that the actual
        # x-values are identical throughout all sets! We could try some smart things
        # to allow for non-matching data sets to be plotted, but for now, we just
        # check if the data sets are o.k. and cope with differently-ordered x-values.

        # The first loop is to fix the data sets if they have different set of x-values.
        # First, create an array that contains *all* x-values (of all data sets). Then,
        # sort this array and insert the missing x-values into each data set (at the same
        # location!)
        x_vals = []
        for dset in range(len(self.data_sets)):
            for d_idx in range(len(self.data_sets[dset][X])):
                if self.data_sets[dset][Y][d_idx] != None:
                    x_val = self.data_sets[dset][X][d_idx]
                    if not x_val in x_vals:
                        x_vals.append(x_val)
        x_vals.sort()
        for dset in range(len(self.data_sets)):
            x_idx = 0
            for x_val in x_vals:
                if not x_val in self.data_sets[dset][X]:
                    # insert missing x-value with a dummy y-value
                    self.data_sets[dset][X].insert(x_idx, x_val)
                    self.data_sets[dset][Y].insert(x_idx, None)
                else:
                    # make sure the existing x-value is at the correct location
                    d_idx = self.data_sets[dset][X].index(x_val)
                    if d_idx != x_idx:
                        y_val = self.data_sets[dset][Y][d_idx]
                        self.data_sets[dset][X].pop(d_idx)
                        self.data_sets[dset][Y].pop(d_idx)
                        self.data_sets[dset][X].insert(d_idx, x_val)
                        self.data_sets[dset][Y].insert(d_idx, y_val)
                x_idx = x_idx + 1

        # Now, loop over all data sets again to determine the plotting offsets and width on the x-axis.
        for dset in range(len(self.data_sets)):
            set_pts = {}
            for pos_idx in range(len(self.data_sets[dset][X])):
                # Make sure that all data points are valid!
                if self.data_sets[dset][Y][pos_idx] != None:
                    x_pos = pos_idx - x_pos_off + dset*x_pos_inc
                    data_line = "%f " % x_pos
                    for d_vector in range(1, len(self.data_sets[dset])):
                        data_line += "%s " % str(self.data_sets[dset][d_vector][pos_idx])
                    set_pts[pos_idx] = data_line + "\n"
            if len(set_pts) > 0:
                for i in range(len(x_vals)):
                    if set_pts.has_key(i):
                        data_pts.append(set_pts[i])
                data_pts.append("e\n") # End-of-dataset marker
            else:
                return data_pts

        cmd_strs.extend(data_pts)
        return cmd_strs
        
    def _setup_cmds_points(self):
        print "#* WARNING: type 'points' is not supported. Use type='graphs' with style='points'"
        return ("set style data dots")
     
    def _plot_points(self):
        # TODO: not implemented (see above)
        cmd_strs = []
        return cmd_strs
     
    def _setup_cmds_graphs(self):
        cmd_strs = []
        return cmd_strs
     
    def _plot_graphs(self):        
        cmd_strs = []
        data_pts = []
        X = 0
        Y = 1

        line_width = "lw %d" % self.elmtsize

        plot_cmdline = "%s " % self.plot_cmd
        for dset in range(len(self.data_sets)):
            data_title = self._clean_str(self.data_titles[dset])

            elmt_fmt = line_width
            if self.plot_styles[dset] in ("dots", "points", "linespoints"):
                elmt_fmt += " ps %d" % self.elmtsize

            plot_cmdline += "'-' %s title '%s' %s with %s %s," % \
                        (mk_using_str(len(self.data_sets[dset])),
                         mk_enhanced_gp(data_title),
                         self._build_axis_str(dset),
                         self.plot_styles[dset], elmt_fmt)
        plot_cmdline = rstrip(plot_cmdline, ',') + "\n"
        cmd_strs.append(plot_cmdline)

        for dset in range(len(self.data_sets)):
            n_prev = None
            blank_cnt = 0
            data_cnt = 0
            for d_idx in range(len(self.data_sets[dset][X])):
                data_line = ""
                line_is_valid = True
                insert_blank = False
                for d_vector in range(len(self.data_sets[dset])):
                    # Make sure that all data points are valid!
                    n = self.data_sets[dset][d_vector][d_idx]
                    if n is None:
                        line_is_valid = False
                    else:
                        data_line += "%s " % str(n)
                        # Need to add empty lines as separator for gridded 3D data plots (don't want lines).
                        # This requires that the first parameter column is sorted.
                        if self.ndims == 3 and d_vector == 0:
                            if n_prev is None:
                                n_prev = n
                            elif n_prev != n:
                                insert_blank = True
                                n_prev = n
                            
                if line_is_valid:
                    if insert_blank:
                        blank_cnt += 1
                        data_pts.append("\n")
                    data_pts.append(data_line + "\n")
                    data_cnt += 1
            if self.ndims == 3 and (blank_cnt == 0 or blank_cnt == data_cnt - 1):
                # It makes no sense to plot one-dimensional datasets in 3D. The reason for this situation
                # will most likely be unsorted data. However, this is not a bullet-proof check: data that
                # is sorted in some (but not the right) way will not trigger this exception.
                raise DataError, "can not plot one-dimensional input data in 3D (missing sort-<operator>?)"
            if len(data_pts) > 0:
                data_pts.append("e\n") # End-of-dataset marker
            else:
                return data_pts

        cmd_strs.extend(data_pts)
        return cmd_strs

    def _setup_cmds_steps(self):
        cmd_strs = []
        return cmd_strs
     
    def _plot_steps(self):
        return self._plot_graphs()

    def _setup_cmds_boxes(self):
        cmd_strs = []
        cmd_strs.append("set boxwidth 0.9 relative\n")
        cmd_strs.append("set style fill solid 1.0\n")
        return cmd_strs

    def _plot_boxes(self):
        self._plot_graphs()
        return

    def _setup_target(self, target, prefix):
        cmd_strs = []
        color = ""
        if self.use_color:
            color = "color"
            
        if target == "screen":
            cmd_strs.append('set terminal %s font "helvetica-%d"\n' % (self.screen_term, self.fontsize))
        elif target == "png":
            cmd_strs.append("set terminal png font helvetica %d enhanced \n" % (self.fontsize))
            cmd_strs.append("set size ratio 0.5  2.00,1.00\n")
        elif target == "ps":
            cmd_strs.append('set terminal postscript enhanced %s "Helvetica" %d\n' % (color, self.fontsize))
        elif target == "eps":
            cmd_strs.append('set terminal postscript eps enhanced %s "Helvetica" %d\n' % (color, self.fontsize))
            cmd_strs.append("set size 0.8\n")
        elif target == "pdf":
            # fontssize needs to be cut down for PDF for whatever reason!
            self.fontsize /= 2
            cmd_strs.append('set terminal pdf enhanced fname "Helvetica" fsize %d\n' % self.fontsize)
        else:
            raise SpecificationError, "unsupported gnuplot target '%s'" % target

        if target != "screen":
            cmd_strs.append("set output '%s.%s'\n" % (prefix, target))
            if be_verbose():
                print "#* writing output to '%s.%s'" % (prefix, target)            
            
        return cmd_strs

    def _setup_common(self):
        cmd_strs = []

        if self.title:
            cmd_strs.append('set title "%s"\n' % self.title)
        for dim in ('x', 'y', 'z'):
            for place in ('', '2'):
                axis_idx = (dim, place)                
                if self.axis[axis_idx].set:
                    if self.axis[axis_idx].idx_list != None:
                        tic_str = "("
                        for tic in self.axis[axis_idx].idx_list:
                            tic_str += str(tic) + ","
                        tic_str = rstrip(tic_str, ',') + ')'
                        cmd_strs.append("set %s%stics %s\n" % (dim, place, tic_str))
                    else:
                        cmd_strs.append("set %s%srange [%d:%d]\n" % (dim, place, self.axis[axis_idx].min, \
                                                                     self.axis[axis_idx].max))
                        cmd_strs.append("set %s%stics autofreq\n" % (dim, place))
                if self.label.has_key(axis_idx):
                    cmd_strs.append('set %s%slabel "%s"\n' % (dim, place, mk_enhanced_gp(self.label[axis_idx])))
                if self.logscale.has_key(axis_idx):
                    cmd_strs.append("set logscale %s%s %d\n" % (dim, place, self.logscale[axis_idx]))

            if self.axis_cnt[dim] > 1:
                cmd_strs.append("set %stics nomirror\n" % dim)
                cmd_strs.append("set %s2tics nomirror\n" % dim)

        for opt in self.set_opts:
            cmd_strs.append("set %s\n" % opt)
            
        return cmd_strs                             

    def _gather_cmds(self, target, prefix):
        gp_cmds = []
        gp_cmds.extend(self._setup_target(target, prefix))
        gp_cmds.extend(self._setup_common())
        setups_called = []
        for t in self.plot_types:
            if not t in setups_called:
                setups_called.append(t)
                gp_cmds.extend(eval("self._setup_cmds_"+t)())

        # Only for bar plotting, a separate plotting function has to be called. But if bars are
        # to be plotted, nothing else can be plotted (a current limitation)
        if setups_called[0] == "bars":
            plot_cmds = self._plot_bars()
        else:
            plot_cmds = self._plot_graphs()
        if len(plot_cmds) > 0:
            gp_cmds.extend(plot_cmds)
            return gp_cmds
        else:
            print "#* ERROR: no data to plot" 
            return []

    def plot(self, target="screen", prefix=None):
        if len(self.data_sets) > 0:
            try:
                self.gnuplot = popen('%s %s' % (self.gnuplot_cmd, self.gp_opts), 'w')
            except:
                print "#* ERROR: can not start '%s'. Make sure it is found in $PATH." % self.gnuplot_cmd
                exit(1)

            gnuplot_cmds = self._gather_cmds(target, prefix)
            for cmd in gnuplot_cmds:
                self.gnuplot.write(cmd)
            self.gnuplot.flush()
            
            if prefix:
                try:
                    fname = prefix+".gp"
                    gp_file = open(fname, 'w+')
                except IOError, error_msg:
                    print "#* ERROR: can not open output file '%s' for writing." % fname
                    print "  ", error_msg
                    exit(1)
                if be_verbose():
                    print "#* writing gnuplot command file '%s.gp'" % (prefix)            
                for cmd in gnuplot_cmds:
                    gp_file.write(cmd)
                gp_file.close()

        return

    def save(self, target="pdf", prefix=None):
        if prefix is None:
            if self.title:
                prefix = self.title
            else:
                self.gnuplot = stdout

        if self.gnuplot is None:
            try:
                fname = prefix+".gp"
                self.gnuplot = open(fname, 'w+')
            except:
                print "#* ERROR: can not open output file '%s' for writing." % fname
                exit(1)

        gnuplot_cmds = self._gather_cmds(target, prefix)
        for cmd in gnuplot_cmds:
            self.gnuplot.write(cmd)
        self.gnuplot.flush()

        return
    
    def close(self):
        self.gnuplot.close()
        return
        

        
