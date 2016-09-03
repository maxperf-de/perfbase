# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de> 
#
# pb_outputs - all available output classes
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

from pb_query_classes import *
from pb_common import *
from pb_plotutil import *

from sys import stdout, exit
import time
import re
import ooolib

# base class for all output classes
class output(data):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        data.__init__(self, elmnt_tree, nodes, db)

        self.name = elmnt_tree.get("id")
        if not self.name: 
            self.name = str(hash(elmnt_tree))
        self.type = "output"
        self.title = mk_label(elmnt_tree.get("title"), nodes)
        self.inp_label_type = {}
        self.fd = None

        self.inputs = []
        inp_ids = elmnt_tree.findall('input')
        if not inp_ids:
            raise SpecificationError, "each <ouput> needs to have at least one <input> entry"
        for inp in inp_ids:
            inp_list = []
            if sweep_alias != None:
                if sweep_alias.has_key(inp.text):
                    inp_list.extend(sweep_alias[inp.text])
            if len(inp_list) == 0:
                if not nodes.has_key(inp.text):
                    raise SpecificationError, "unknown <input> '%s' in <ouput>" % inp.text
                inp_list.append(inp.text)
            for inp_name in inp_list:
                self.inputs.append(nodes[inp_name])
                inp_node = nodes[inp_name]
                # check for a label for this plot
                self.inp_label_type[inp_node] = inp.get("label")
                if self.inp_label_type[inp_node] is None:
                    self.inp_label_type[inp_node] = "parameter"

        # To unify the output filename, we append the filters passed up from the 
        # parameters, or replace macros with content etc.
        # This code should be moved into a generic function!
        self.filename = None
        fname_node = elmnt_tree.find("filename")
        if fname_node != None:
            self.filename = fname_node.text
            unify_mode = get_attribute(fname_node, "<ouput> %s" % self.name,
                                       "unify", "no", ('no', 'filter', 'sweep', 'fixed'))
            self.fname_unify = []
            if unify_mode == "filter":
                for inp_filter in self.filters.itervalues():
                    for f in inp_filter:
                        f = f.strip()
                        f = f.replace("'", '')
                        f = f.replace(' = ', '=')
                        f = f.replace('  ', '_')
                        f = f.replace(' ', '_')

                        for t in f.split(pb_label_sep):
                            if not t in self.fname_unify:
                                self.fname_unify.append(t)
            elif unify_mode == "sweep":
                for s in sweep_alias.itervalues():
                    self.fname_unify.append(s.split(pb_sweep_suffix)[1])
            elif unify_mode == "fixed":
                self.filename = mk_label(self.filename, nodes)
        
        # Determine the data that we get from the inputs. We might need
        # to rename identically name values to avoid conflicts in the
        # input tables.
        self.input_params = {}   # mapping input -> list of its parameter infos
        self.input_results = {}  # mapping input -> list of its result infos
        self.src_tables = {}    # mapping input -> output table name
        self.filters = {}
        
        for inp in self.inputs:
            self.input_params[inp] = []
            self.input_results[inp] = []
            self.filters[inp] = []
            
            col_names = {}
            idx = 0
            for ip in inp.get_param_info():
                new_ip = []
                new_ip.extend(ip)
                if col_names.has_key(ip[0]):
                    idx += 1
                    new_ip[0] = ip[0] + str(idx)

                col_names[new_ip[1]] = True
                self.input_params[inp].append(new_ip)

            for ir in inp.get_result_info():
                new_ir = []
                new_ir.extend(ir)
                if col_names.has_key(ir[0]):
                    idx += 1
                    new_ir[0] = ir[0] + str(idx)                  
                if new_ir[6]:
                    self.filters[inp].extend(new_ir[6].split(pb_label_sep))

                col_names[new_ir[0]] = True
                self.input_results[inp].append(new_ir)

            self.src_tables[inp] = inp.get_table_name()

        self.have_shutdown = False
        return
    
    def shutdown(self, db):
        if not self.have_shutdown:
            for inp in self.inputs:
                drop_query_table(db, self.src_tables[inp])
                inp.shutdown(db)
            if self.fd != stdout and self.fd != None:
                self.fd.close()

            self.have_shutdown = True
        return        
    
    def perform_query(self, db):
        if do_profiling():
            t0 = time.clock()

        for inp in self.inputs:
            inp.perform_query(db)

        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['perform_query'].append(t0)
        return

    def update_filters(self, inp):
        # check for updated result filter information
        for f in inp.update_filters():
            for ir in self.input_results[inp]:
                if ir[6].count(f[0]) > 0:
                    ir[6] = ir[6].replace(f[0], f[1], 1)
                    
        for flt in self.filters[inp]:
            if flt.count(pb_filter_str) > 0 and flt.count(f[0]) > 0:
                self.filters[inp].remove(flt)
                self.filters[inp].append(flt.replace(pb_filter_str, f[1], 1))
        return
    
class raw_binary_output(data):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        return


class netcdf_output(data):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        return


class hdf5_output(data):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        return


class grace_output(data):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        return


class latex_output(data):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        return


class opendoc_output(output):    
    """Create OpenDocument spreadsheets (i.e. for OpenOffice Calc),
    using ooolib module.  There are a lot of different ways how the
    data (vectors) coming from the <input>'s can be mapped into the
    2-dimensional sheet, with multiple sheets being the 3rd
    dimension. Some cases:    

    1. Single <input>, no sweeps, parameter and result data in vector:
    single sheet, two columns A and B for the data. The filters are written
    above into a single cells each. Plain and simple.

    2. Single <input>, with sweeps, parameter and result data in vector:
    Put parameter data once in column A, then the result data into
    columns B, C, ..., with the varied filter condition into the respective
    column header.

    3. Like 1. or 2., but with multiple <input>'s: create a new sheet
    for every input, then proceed as done for 1. and 2.

    4  multiple <input>'s, no sweep, but with same parameters and results:
    This should be handled like 2., but perfbase needs to determine by
    itself that this makes sense. It's a refinement of case 3.
    """    
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        if do_debug():
            print "#* DEBUG: initalizing output class 'opendoc'"
        output.__init__(self, elmnt_tree, nodes, db)        
        return


    def strip_label(self, lbl):
        # TODO: could use regexp here
        while lbl.endswith(pb_label_sep):
            lbl = lbl[:-len(pb_label_sep)]
        return lbl
           
    
    def mk_filterlabel(self, filters):
        # create a row label from a list of filters that are effective 
        f = ""
        for v in filters:
            f += v + ", "
        return f[:-2]


    def mk_unitlabel(self, label, unit):
        return self.strip_label(label) + " ["+ unit +"]"


    def mksheet_single_vector(self, doc, col_data,
                              col_labels, col_units, col_types,
                              col_filters, common_filters):
        # Create a single-page spreadsheet with one or more parameter vectors
        # and one or more result vectors, arranged from left to right (straight
        # forward). Filter conditions are printed separately at the top of the page.
        
        col_idx = 1
        row_idx = 1

        # print common filters
        doc.set_cell_property('fontsize', '12')
        doc.set_cell_property('bold', True)
        doc.set_cell_property('color', '#000000')
        doc.set_cell_value(col_idx, row_idx, "string", "Parameters are:")
        row_idx += 1

        doc.set_cell_property('bold', False)
        doc.set_cell_property('color', '#ff0000')
        for f in common_filters:
            doc.set_cell_value(1, row_idx, "string", f)
            row_idx += 1
        row_idx += 1
        for val in col_filters.values():
            if len(val) > 0:
                row_idx += 1
                break

        # print column labels
        doc.set_cell_property('color', '#000000')
        doc.set_cell_property('fontsize', '10')
        doc.set_cell_property('background', '#cccccc')
        doc.set_cell_property('bold', True)
        for l in col_labels:
            full_label = self.mk_unitlabel(l, col_units[l])
            if col_filters.has_key(l):
                col_filter = ""
                for f in col_filters[l]:
                    col_filter += f
                doc.set_cell_value(col_idx, row_idx-1, "string", col_filter)
            doc.set_cell_value(col_idx, row_idx, "string", full_label)
            col_idx += 1
        col_idx = 1

        # don't forget the data
        data_idx = row_idx + 1
        doc.set_cell_property('bold', False)
        doc.set_cell_property('background', '#ffffff')
        for l in col_labels:
            row_idx = data_idx
            for d in col_data[l]:
                doc.set_cell_value(col_idx, row_idx, col_types[l], d)
                row_idx += 1
            col_idx += 1

        return


    def mksheet_single_scalar_1D(self, doc, col_data,
                                 col_labels, col_units, col_types,
                                 col_filters, common_filters):
        # Create a single page spreadsheet for multiple single result values with one
        # dimension of the  array representing a varying filter conditions, and the other
        # dimension the different result values. Constant filter conditions
        # (that apply to all result values) are printed separately on top.
        
        col_idx = 1
        row_idx = 1
        
        # print common filters
        doc.set_cell_property('fontsize', '12')
        doc.set_cell_property('bold', True)
        doc.set_cell_property('color', '#000000')
        doc.set_cell_value(col_idx, row_idx, "string", "Parameters are:")
        row_idx += 1

        doc.set_cell_property('bold', False)
        doc.set_cell_property('color', '#ff0000')
        for f in common_filters:
            doc.set_cell_value(1, row_idx, "string", f)
            row_idx += 1
        if len(common_filters) > 0:
            row_idx += 1

        # The column filters are use as row labels, the result
        # values with their content labels are stored as column labels.
        c_lbls = []
        r_lbls = []
        for l in col_labels:
            if col_filters.has_key(l):
                if len(col_filters[l]) > 0:
                    f = self.mk_filterlabel(col_filters[l])
                    if not f in r_lbls:
                        r_lbls.append(f)
            f = self.mk_unitlabel(l, col_units[l])
            if f not in c_lbls:
                c_lbls.append(f)
        start_col = 1
        if len(r_lbls) > 0:
            start_col += 1

        col_idx = 0
        doc.set_cell_property('fontsize', '10')
        doc.set_cell_property('background', '#cccccc')
        doc.set_cell_property('color', '#000000')
        doc.set_cell_property('bold', True)
        doc.set_cell_value(col_idx, row_idx, "string", " ")
        for l in c_lbls:
            doc.set_cell_value(start_col + col_idx, row_idx, "string", l)
            col_idx += 1

        row_idx += 1
        start_row = row_idx
        col_idx = 1
        for l in r_lbls:
            doc.set_cell_value(col_idx, row_idx, "string", l)
            row_idx += 1

        # don't forget the data
        doc.set_cell_property('bold', False)
        doc.set_cell_property('background', '#ffffff')
        col_idx = 0
        row_idx = 0
        for l in col_labels:
            doc.set_cell_value(start_col+col_idx, start_row+row_idx, col_types[l], col_data[l][0])
            row_idx += 1
            if row_idx >= len(r_lbls):
                col_idx += 1
                row_idx = 0

        return


    def mksheet_single_scalar_2D(self, doc, col_data,
                                 col_labels, col_units, col_types,
                                 col_filters, common_filters):
        # Create a single page spreadsheet with a 2D-array for single result values,
        # with the two dimensions of the array representing two varying filter
        # conditions. Constant filter conditions (that apply to all result values)
        # are printed sepaately on top.
        
        col_idx = 1
        row_idx = 1
        
        # print common filters
        doc.set_cell_property('fontsize', '12')
        doc.set_cell_property('bold', True)
        doc.set_cell_property('color', '#000000')
        doc.set_cell_value(col_idx, row_idx, "string", "Parameters are:")
        row_idx += 1

        doc.set_cell_property('bold', False)
        doc.set_cell_property('color', '#ff0000')
        for f in common_filters:
            doc.set_cell_value(1, row_idx, "string", f)
            row_idx += 1
        if len(common_filters) > 0:
            row_idx += 1

        # Print the result value. In some cases, there are one or more parameters
        # in columns before the result value. We assume the result value is in the
        # rightmost (last) column.
        # TODO: make sure that we only have a single result value!
        l = col_labels[-1:][0]
        doc.set_cell_property('bold', True)
        doc.set_cell_property('color', '#000000')
        full_label = "Results are "+ self.mk_unitlabel(l, col_units[l])
        doc.set_cell_value(col_idx, row_idx, "string", full_label)

        # One set of the column filters are the column labels, the other
        # set is of filters are the labels for the rows.
        # We also need to take care to map the data correctly to the 
        # cell it belongs to (according to the row- and column-filter
        # conditions)!
        c_lbls = []
        r_lbls = []
        map_label_row = -1
        map_label_col = -1
        auto_row_inc = 0
        auto_col_inc = 0
        col_constant = False
        row_constant = False
        data_mapper = {}
        for l in col_labels:
            f = col_filters[l][0]
            if not f in c_lbls:
                c_lbls.append(f)
                map_label_col += 1

                if col_constant:
                    map_label_row = -1
                    auto_row_inc = 1
                col_constant = False
            else:
                col_constant = True

            f = col_filters[l][1]
            if not f in r_lbls:
                r_lbls.append(f)
                map_label_row += 1

                if row_constant:
                    map_label_col = -1
                    auto_col_inc = 1
                row_constant = False
            else:
                row_constant = True

            map_label_col += auto_col_inc
            map_label_row += auto_row_inc
            data_mapper[l] = [map_label_col, map_label_row]

        row_idx += 1
        doc.set_cell_property('fontsize', '10')
        doc.set_cell_property('background', '#cccccc')
        doc.set_cell_value(col_idx, row_idx, "string", " ")
        col_idx = 2
        for l in c_lbls:
            doc.set_cell_value(col_idx, row_idx, "string", l)
            col_idx += 1
        row_idx += 1
        start_row = row_idx
        col_idx = 1
        for l in r_lbls:
            doc.set_cell_value(col_idx, row_idx, "string", l)
            row_idx += 1
        row_idx = start_row

        # don't forget the data
        col_idx = 2
        doc.set_cell_property('bold', False)
        doc.set_cell_property('background', '#ffffff')
        for l in col_labels:
            d = col_data[l][0]
            doc.set_cell_value(col_idx+data_mapper[l][0], 
                               row_idx+data_mapper[l][1], 
                               col_types[l], d)

        return


    def store_data(self, db):
        global pb_label_sep

        if do_profiling():
            t0 = time.clock()

        for inp in self.inputs:
            inp.store_data(db)

        doc = ooolib.Calc(self.name)
        doc.set_meta('title', self.name)
        # Unfortunately, synopsis and description are not part of the
        # output object, but of the query description - therefore not set
        # at this point. Anyway...
        if self.synopsis != None:
            doc.set_meta('subject', self.synopsis)
        if self.description != None:
            doc.set_meta('description', self.description)
        doc.set_meta('creator', getenv("USER"))

        doc.set_meta('user1name', 'perfbase version')
        doc.set_meta('user1value', pb_release_version)

        crs = db.cursor()

        # We need to create a representation of the spreadsheet
        # in memory, before we actually dump it to ooolib to create
        # the OpenDoc document. This will allow us to check which
        # content we already have in the sheets, and add output
        # from other <input>s in a meaningful way: 
        # 1. For parameter sweep which results in data vectors as input,
        # we should attach a new column to an existing table with the
        # respective filter condition in the headline 
        # 2. If the <inputs> do deliver scalar values, we should arrange
        # them in a table where two filters (parameter sweeps) span across
        # the columns and rows.
        # 3. If the data from a new <input> can not be related to previous
        # <input>s, we should create a new sheet.
        #
        col_labels = [] # column labels, ordered
        col_units = {}  # column units
        col_types = {} # python data types, indexed by column label
        col_filters = {} # per-column filters, indexed by column label
        col_data = {} # lists of column data, indexed by column label
        row_filters = [] # per-row filters, ordered, may be empty
        common_filters = [] # list of common filters for all values
        multi_labels = [] # column labels used more than once - check for identity lateron
        inp_labels = {} # maps input to list of column (labels) from this input
        for inp in self.inputs:
            self.update_filters(inp)

            # Get labels. Check for parameters that have already been used by
            # other inputs - they should be re-used and just some more columns
            # added.
            inp_labels[inp] = []
            for i in self.input_params[inp]:
                clabel = i[1] # the parameter name
                if clabel in col_labels:
                    if clabel not in multi_labels:
                        multi_labels.append(clabel)
                    while clabel in col_labels:
                        clabel = clabel + pb_label_sep
                col_labels.append(clabel)
                col_units[clabel] = i[4]
                col_types[clabel] = i[3]
                inp_labels[inp].append(clabel)
            for i in self.input_results[inp]:
                clabel = i[1]
                while clabel in col_labels:
                    clabel = clabel + pb_label_sep
                col_labels.append(clabel)
                col_units[clabel] = i[4]
                col_types[clabel] = i[3]
                inp_labels[inp].append(clabel)

        # Sort the column labels to ensure a single order where labels for the same column
        # coming from different sources/operators are always grouped together like: A, A###, 
        # B, B### (### being pb_label_sep). Otherwise, this would only be the case for 
        # parameters coming from sweep filters, but not for parameters coming from independent 
        # filters.
        col_labels.sort()

        for inp in self.inputs:
            sqlexe(crs, "SELECT * FROM %s" % self.src_tables[inp])
            db_rows = crs.fetchall()

            # store data
            for l in inp_labels[inp]:
                col_data[l] = []
            for r in db_rows:
                # data starts at index 4
                r_idx = 4
                for l in inp_labels[inp]:
                    col_data[l].append(r[r_idx])
                    r_idx += 1
            
            # store filters
            for i in self.input_results[inp]:
                clabel = i[1]
                while clabel in col_filters.keys():
                        clabel = clabel + pb_label_sep                    
                col_filters[clabel] = []
                for f in self.filters[inp]:
                    col_filters[clabel].append(f.replace("'",""))

        # determine filters common to all columns
        ref_filters = col_filters[clabel]
        for ref_flt in ref_filters:
            is_common = True
            for val in col_filters.values():
                if not ref_flt in val:
                    is_common = False
                    break
            if is_common:
                # move this filter to common filters
                common_filters.append(ref_flt)

        for f in common_filters:
            for val in col_filters.values():
                val.remove(f)

        # Check if parameter columns that were used multiple times 
        # are actually identical. 
        del_labels = []
        for ml in multi_labels:
            for l in col_labels:
                if l == ml:
                    continue
                if self.strip_label(l) == ml and col_data[l] == col_data[ml]:
                    del col_data[l]
                    del_labels.append(l)
        for l in del_labels:
            col_labels.remove(l)

        # If there are columns for the same label with differing data, we 
        # can either create separate tables for the respective inputs, or
        # merge the parameter colums, creating gaps in the respective
        # result columns. CHECK: is there an automatic criterium for this,
        # or should this be determined explicitely?
        
                            
        # Finally, create the spreadsheet, using the appropiate method.
        sheet_type="unknown"
        for l in col_labels:
            if len(col_data[l]) > 1:
                sheet_type = "single_vector"
                break
        if sheet_type == "unknown":
            if len(col_filters[clabel]) == 2:
                sheet_type = "single_scalar_2D"
            elif len(col_filters[clabel]) <= 1:
                sheet_type = "single_scalar_1D"
            else:
                raise StandardError, "No appropiate OpenDoc spreadsheet format available."

        eval("self.mksheet_"+sheet_type)(doc, col_data,
                                         col_labels, col_units, col_types,
                                         col_filters, common_filters)        
        doc.save(self.filename+".ods")
        return


class xml_output(output):
    """XML output format looks like:
    <output title="Latency over Messagesize">
       <data>
          <filter>T > 5</filter>
          <filter>N = 0</filter>
          <dataset>
             <value name="S">15</value>
             <value name="L">40</value>
          </dataset>
          <dataset>
              ...
          </dataset>
          ...
       </data>
       <data>
          <filter>T > 5</filter>
          <filter>N = 1</filter>
          <dataset>
             <value name="S">25</value>
             <value name="L">50</value>
          </dataset>
       </data>
    </output>                    
    """
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        if do_debug():
            print "#* DEBUG: initalizing output class 'xml'"

        output.__init__(self, elmnt_tree, nodes, db)
        return

    def store_data(self, db):
        global pb_label_sep

        if do_profiling():
            t0 = time.clock()

        for inp in self.inputs:
            inp.store_data(db)

        self.fd = stdout
        if self.filename:
            try:
                fname = self.filename+".xml"
                self.fd = open(fname, 'w+')
            except IOError, error_msg:
                print "#* ERROR: can not open output file '%s' for writing." % fname
                print "  ", error_msg
                sys.exit(1)
                
        crs = db.cursor()
        prev_header = ""
        prev_data_title = ""

        # We don't use ElementTree to generate the XML - this would require keeping all data
        # in memory once more, which may be a problem for large data output.
        print >>self.fd, "<output>"
        for inp in self.inputs:
            # check for updated result filter information
            for f in inp.update_filters():
                for ir in self.input_results[inp]:
                    if ir[6].count(f[0]) > 0:
                        ir[6] = ir[6].replace(f[0], f[1], 1)
                        
                for flt in self.filters[inp]:
                    if flt.count(pb_filter_str) > 0 and flt.count(f[0]) > 0:
                        self.filters[inp].remove(flt)
                        self.filters[inp].append(flt.replace(pb_filter_str, f[1], 1))

            sqlexe(crs, "SELECT * FROM %s" % self.src_tables[inp])
            db_rows = crs.fetchall()

            # CHECK: For some reason we come through here more often than we should..
            # the second time has no rows.  So, if we have no rows, quit now
            # to avoid printing extra output tags.
            if len(db_rows) == 0:
                break
            
            print >>self.fd, "  <data>"
            # print filters
            for f in self.filters[inp]:
                print >>self.fd, "    <filter>%s</filter>" % f
                
            # print data
            for r in db_rows:
                v = 4
                print >>self.fd, "    <dataset>"
                for i in self.input_params[inp]:
                    if v == len(r):
                        raise DataError, "XML output has more parameter values than data columns"
                    
                    elem = i[1]
                    unit = ""
                    if i[4]:
                        unit = ' unit="%s"' % i[4]
                    print >>self.fd, '      <value name="%s"%s>%s</value>' % (elem, unit, r[v])
                    v += 1
                for i in self.input_results[inp]:
                    if v == len(r):
                        raise DataError, "XML output has more result values than data columns"
                    
                    elem = i[1]
                    unit = ""
                    if i[4]:
                        unit = ' unit="%s"' % i[4]
                    print >>self.fd, '      <value name="%s"%s>%s</value>' % (elem, unit, r[v])
                    v += 1
                print >>self.fd, "    </dataset>"
            print >>self.fd, "  </data>"
        print >>self.fd, "</output>"

        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)
        return


class raw_text_output(output):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        if do_debug():
            print "#* DEBUG: initalizing output class 'raw_text'"
        output.__init__(self, elmnt_tree, nodes, db)
        return

    def store_data(self, db):
        global pb_label_sep

        if do_profiling():
            t0 = time.clock()

        for inp in self.inputs:
            inp.store_data(db)

        self.fd = stdout
        if self.filename:
            if len(self.fname_unify) > 0:
                for f in self.fname_unify:
                    self.filename += '_' + f
            try:
                fname = self.filename+".dat"
                self.fd = open(fname, 'w+')
            except IOError, error_msg:
                print "#* ERROR: can not open output file '%s' for writing." % fname
                print "  ", error_msg
                sys.exit(1)
                
        crs = db.cursor()
        prev_header = ""
        prev_data_title = ""
        for inp in self.inputs:
            # check for updated result filter information
            for f in inp.update_filters():
                for ir in self.input_results[inp]:
                    if ir[6].count(f[0]) > 0:
                        ir[6] = ir[6].replace(f[0], f[1], 1)
                        
                for flt in self.filters[inp]:
                    if flt.count(pb_filter_str) > 0 and flt.count(f[0]) > 0:
                        self.filters[inp].remove(flt)
                        self.filters[inp].append(flt.replace(pb_filter_str, f[1], 1))

            sqlexe(crs, "SELECT * FROM %s" % self.src_tables[inp])
            db_rows = crs.fetchall()

            r_info = self.input_results[inp][0]
            if len(self.input_params[inp]) > 0:
                p_info = self.input_params[inp][0]
            else:
                # no parameter data vector available! 
                p_info = None

            if len(db_rows) > 0:
                # print header            
                data_title = ""
                lbl_type = self.inp_label_type[inp].strip()
                if not lbl_type in ('empty', 'value', 'full', 'parameter', 'input_id', 'explicit', 'fulltitle', 'title'):
                    print "#* WARNING: <output> '%s': invalid content '%s' for attribute 'label' in <input> '%s'\n" \
                          % (self.name, lbl_type, inp.get_name())
                if lbl_type == "parameter":
                    data_title = "# "
                    for f in self.filters[inp]:
                        data_title += f + "  "
                if lbl_type == "input_id":
                    data_title = "# " + inp.get_name().replace('.', ' ')

                if lbl_type != "empty":
                    header = "# "
                    for i in self.input_params[inp]:
                        h = i[1]+"["+i[4]+"]\t"
                        header = header + h.replace(pb_label_sep, '  ')
                    for i in self.input_results[inp]:
                        h = i[1]+"["+i[4]+"]\t"
                        header = header + h.replace(pb_label_sep, '  ')

                    if header != prev_header or data_title != prev_data_title:
                        if len(data_title) > 0 and data_title != "# ": 
                            print >>self.fd, data_title
                            prev_data_title = data_title
                        if len(header) > 0:
                            print >>self.fd, header
                            prev_header = header

                # print data
                for r in db_rows:
                    # start at '4' to skip index and data source columns
                    for v in range(4,len(r)):
                        print >>self.fd, r[v],
                        print >>self.fd, "\t",
                    print >>self.fd, ""

        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)
        return


class gnuplot_output(data):
    def __init__(self, elmnt_tree, nodes, db, sweep_alias = None):
        if do_debug():
            print "#* DEBUG: initalizing output class 'gnuplot'"

        data.__init__(self, elmnt_tree, nodes, db)

        self.updated_filters = []
        self.filters = []
        self.plot_options = []
        self.fname_unify = []
        self.sweep_alias = sweep_alias
        nbr_params = -1
        nbr_results = -1
        
        self.valid_plot_styles = { 'graphs':'linespoints', 'points':'points',
                                   'boxes':'boxes', 'bars':'boxes',
                                   'steps':'histeps' }
        self.gp = None
        self.name = elmnt_tree.get("id")
        if not self.name: 
            self.name = str(hash(elmnt_tree))
        self.type = "output"
        self.title = mk_enhanced_gp(mk_label(elmnt_tree.get("title"), nodes))
        self.filterstring = elmnt_tree.get("filterstring")
        if self.filterstring is None:
            default_label_type = "full"
        else:
            default_label_type = "title"
            
        self.format = get_attribute(elmnt_tree, "<output> %s" % self.name, "format", "screen",
                                    ("screen", "ps", "eps", "pdf", "png"))

        self.ndims = int(get_attribute(elmnt_tree, "<output> %s" % self.name, "dimensions", "2", ("2", "3")))
        self.plot_options.append("ndims %d" % self.ndims)

        self.use_color = True
        if get_attribute(elmnt_tree, "<output> %s" % self.name, "color", "yes", ("yes", "no")) == "no":
            self.use_color = False

        self.default_plot_type = elmnt_tree.get("type")
        if not self.default_plot_type:
            self.default_plot_type = "graphs"
        else:
            if not self.valid_plot_styles.has_key(self.default_plot_type):
                raise SpecificationError, "Invalid content '%s' for <ouput> attribute 'type'" % self.default_plot_type
        self.default_plot_style = elmnt_tree.get("style")
        if not self.default_plot_style:
            self.default_plot_style = self.valid_plot_styles[self.default_plot_type]

        self.ntics = get_attribute(elmnt_tree, "<output> %s" % self.name, "ntics", "-1")
        self.plot_options.append("ntics %s" % self.ntics)

        fontsize = get_attribute(elmnt_tree, "<output> %s" % self.name, "fontsize", "normal",
                                 ('tiny', 'small', 'normal', 'large', 'huge'))
        self.plot_options.append("fontsize %s" % fontsize)
        elmtsize = get_attribute(elmnt_tree, "<output> %s" % self.name, "elements", "normal",
                                 ('tiny', 'small', 'normal', 'large', 'huge'))
        self.plot_options.append("elements %s" % elmtsize)

        dflt_error_plotting = elmnt_tree.get('errors')
        if dflt_error_plotting and dflt_error_plotting != "disable":
            if self.default_plot_style == "boxes":
                raise SpecificationError, "<output> '%s': error plotting for plot type 'bars' not supported." \
                      % self.name
            if self.default_plot_style == 'linespoints':
                self.default_plot_style = 'yerrorlines'
            elif self.default_plot_style == 'points':
                self.default_plot_style = 'yerrorbars'
            else:
                self.default_plot_style = 'boxerrorbars'
            nbr_params = 1
            if dflt_error_plotting == "ydelta":
                nbr_results = 2
            elif dflt_error_plotting == "ylowhigh":
                nbr_results = 3                    

        self.inputs = []
        self.inp_label_type = {}
        self.inp_label_text = {}
        self.inp_plot_type = {}
        self.inp_plot_style = {}
        self.inp_nbr_params = {}
        self.inp_nbr_results = {}
        self.inp_xaxis = {}
        self.inp_yaxis = {}
        inp_ids = elmnt_tree.findall('input')
        if not inp_ids:
            raise SpecificationError, "each <ouput> needs to have at least one <input> entry"
        for inp in inp_ids:
            # For each <input>, we need a list of inputs because due to a sweep, this input may
            # actually consist of a number of independent data series.
            inp_list = []
            if sweep_alias != None and sweep_alias.has_key(inp.text):
                inp_list.append(sweep_alias[inp.text])
            if len(inp_list) == 0:
                if not nodes.has_key(inp.text):
                    raise SpecificationError, "unknown <input> '%s' in <ouput>" % inp.text
                inp_list.append(inp.text)
            for inp_name in inp_list:
                inp_node = nodes[inp_name]

                # check for a label for this plot
                self.inp_label_type[inp_node] = inp.get("label")
                if self.inp_label_type[inp_node] is None or self.inp_label_type[inp_node] == "auto":
                    self.inp_label_type[inp_node] = default_label_type
                if self.inp_label_type[inp_node] == "explicit":
                    self.inp_label_text[inp_node] = inp.get("labeltext")
                    if self.inp_label_text[inp_node] is None:
                        raise SpecificationError, "<ouput> '%s': missing attribute 'labeltext' for 'label=explicit'"\
                              % self.name
                else:
                    self.inp_label_text[inp_node] = ""
                    prefix = inp.get("labelprefix")
                    if prefix:
                        self.inp_label_text[inp_node] += prefix

                # check which axis to use (explicitely)
                self.inp_xaxis[inp_node] = get_attribute(inp, "<input> %s in <output> %s" % (inp.text, self.name),
                                                         "xaxis", "auto", ('top', 'bottom', 'auto'))
                self.inp_yaxis[inp_node] = get_attribute(inp, "<input> %s in <output> %s" % (inp.text, self.name),
                                                         "xaxis", "auto", ('left', 'right', 'auto'))

                # check for individual plot type and style
                self.inp_plot_type[inp_node] = inp.get("type")
                if self.inp_plot_type[inp_node] is None:
                    self.inp_plot_type[inp_node] = self.default_plot_type
                if not self.valid_plot_styles.has_key(self.inp_plot_type[inp_node]):
                    raise SpecificationError, "Invalid content '%s' for <input> attribute 'type'" % self.inp_plot_type[inp_node]
                self.inp_plot_style[inp_node] = inp.get("style")
                if self.inp_plot_style[inp_node] is None:
                    self.inp_plot_style[inp_node] = self.valid_plot_styles[self.inp_plot_type[inp_node]]
                # There are limitations on which types of plots can be plotted within a single chart.
                bar_plotting = False
                for t in self.inp_plot_type.itervalues():
                    if t == "bars":
                        bar_plotting = True
                    elif bar_plotting:
                        raise SpecificationError, "<output> '%s': plot type 'bars' can not be mixed with other plot types." \
                              % self.name

                # finally, the style may need to be adapted for error plotting
                error_plotting = inp.get('errors')
                if error_plotting and error_plotting != "disable":
                    if self.inp_plot_style[inp_node] == "boxes":
                        raise SpecificationError, "<output> '%s': error plotting for plot type 'bars' not supported." \
                              % self.name
                    if nbr_params > 0 and sweep_alias != None and not sweep_alias.has_key(inp.text):
                        raise SpecificationError, "<output> %s: attribute 'errors' must be set either globally or individually!" \
                              % self.name
                    if self.inp_plot_style[inp_node] == 'linespoints':
                        self.inp_plot_style[inp_node] = 'yerrorlines'
                    elif self.inp_plot_style[inp_node] == 'points':
                        self.inp_plot_style[inp_node] = 'yerrorbars'
                    else:
                        self.inp_plot_style[inp_node] = 'boxerrorbars'
                    nbr_params = 1
                    if error_plotting == "ydelta":
                        nbr_results = 2
                    elif error_plotting == "ylowhigh":
                        nbr_results = 3

                # check the correct number of data vectors from this input
                if error_plotting or dflt_error_plotting:
                    self.inp_nbr_params[inp_node] = nbr_params
                    self.inp_nbr_results[inp_node] = nbr_results
                elif self.ndims == 3:
                    self.inp_nbr_params[inp_node] = 2
                    self.inp_nbr_results[inp_node] = 1
                else:
                    self.inp_nbr_params[inp_node] = 1
                    self.inp_nbr_results[inp_node] = 1

                self.inputs.append(inp_node)

        # generic plotting options
        tic_nodes = elmnt_tree.findall("tics")
        for t in tic_nodes:
            tic_axis = get_attribute(t, "<tics> in <output> %s" % self.name, "axis", "x", ('x', 'y', 'z'))
            start_tic = t.findtext("start")
            if start_tic:
                self.plot_options.append("%sticstart %s" % (tic_axis, start_tic))
            inc_tic = t.findtext("increment")
            if inc_tic:
                self.plot_options.append("%sticinc %s" % (tic_axis, inc_tic))

            tic_grid = get_attribute(t, "<tics> in <output> %s" % self.name, "grid", "off", ('on', 'off'))
            self.plot_options.append("%sticgrid %s" % (tic_axis, tic_grid))

        # these are native gnuplot options, either commandline or commandfile
        opt_nodes = elmnt_tree.findall("option")
        self.logscale = {}
        for n in opt_nodes:
            subopts = n.text.split()
            if subopts[0] == "logscale":
                self.logscale[subopts[1][0]] = int(subopts[2])
            self.plot_options.append(n.text)

        self.filename = None
        self.fname_unify_mode = "no"
        fname_node = elmnt_tree.find("filename")
        if fname_node != None:
            self.filename = fname_node.text
            if self.filename and nodes.has_key(self.filename):
                self.filename = nodes[self.filename].get_content()
            self.fname_unify_mode = get_attribute(fname_node, "<ouput> %s" % self.name,
                                                  "unify", "no", ('no', 'filter', 'sweep', 'fixed'))
            if self.fname_unify_mode == "fixed":
                self.filename = mk_label(self.filename, nodes)

        # Determine the data that we get from the inputs. We might need
        # to rename identically name values to avoid conflicts in the
        # input tables.
        self.input_params = {}   # mapping input -> list of its parameter infos
        self.input_results = {}  # mapping input -> list of its result infos
        self.src_tables = {}    # mapping input -> output table name
        filters = []
        
        for inp in self.inputs:
            self.input_params[inp] = []
            self.input_results[inp] = []
            
            col_names = {}
            idx = 0

            inp_params = inp.get_param_info()
            inp_results = inp.get_result_info()
            # We define the following ways to handle the parameter vectors (pv) and result vectors (rv)
            # of the input object:
            # - required #pv == required #rv == 1: (2D plots)
            #   - offered #pv == offered #rv == 1  => straight forward
            #   - offered #pv == 1 and offered #rv > 1 => reuse the single pv for all rv to create multiple graphs
            #   - offered #pv > 1 => ERROR
            # - required #pv == 2 and required #rv == 1: (3D plots)
            #   - offered #pv == 2 and offered #rv == 1  => straight forward
            #   - offered #pv == 2 and offered #rv > 1 => reuse the single pv for all rv to create multiple graphs
            #   - offered #pv > 2 => ERROR
            # - required #rv > 1 (and any required #pv): (2D error plots)
            #   - #rv and #pv offered and required need to match, anything else is an ERROR            
            if self.inp_nbr_params[inp] >= 1 and self.inp_nbr_results[inp] == 1:
                if inp_params is None:
                    raise SpecificationError, "<output> '%s': invalid sweep resolvement for <input> '%s'?" \
                          % (self.name, inp.get_name())
                if len(inp_params) > self.inp_nbr_params[inp]:
                    if be_verbose():
                        print "#* Too many input parameters (found %d, need %d):" % (len(inp_params), self.inp_nbr_params[inp])
                        for i in inp_params:
                            print i[0],
                        print ""
                        print "-> you need to apply a 'show=filter' attribute to some of these <parameter>s!"
                    raise SpecificationError, "<output> '%s': too many parameter vectors for <input> '%s' " \
                          % (self.name, inp.get_name())
                if len(inp_params) < self.inp_nbr_params[inp]:
                    if be_verbose():
                        print "#* Not enough parameters (found %d, need %d):" % (len(inp_params), self.inp_nbr_params[inp])
                        for i in inp_params:
                            print i[0],
                        print ""
                        print "-> you need to apply a 'show=data' or 'show=all' attribute to other <parameter>s!"
                    raise SpecificationError, "<output> '%s': not enough parameter vectors for <input> '%s' " \
                          % (self.name, inp.get_name())
                if be_verbose() and len(inp_results) > 1:
                    print "#* WARNING: <output> '%s': matching parameter vector(s) of <input> '%s' to all result vectors." \
                          % (self.name, inp.get_name())
            else:
                if not (len(inp_params) == self.inp_nbr_params[inp] and len(inp_results) == self.inp_nbr_results[inp]):
                    raise SpecificationError, "<output> '%s': <input> '%s' does not offer required data vectors." \
                          % (self.name, inp.get_name())

            for ip in inp_params:
                new_ip = []
                new_ip.extend(ip)
                if col_names.has_key(ip[0]):
                    idx += 1
                    new_ip[0] = ip[0] + str(idx)
                col_names[ip[0]] = True
                self.input_params[inp].append(new_ip)

            for ir in inp_results:
                if ir[6]:
                    self.filters.append(ir[6])
                new_ir = []
                new_ir.extend(ir)
                if col_names.has_key(ir[0]):
                    idx += 1
                    new_ir[0] = ir[0] + str(idx)
                col_names[new_ir[0]] = True
                self.input_results[inp].append(new_ir)

            self.src_tables[inp] = inp.get_table_name()

        if self.format != "screen" and not self.filename:
            # We need a filename. If the output object is given a name, use it. 
            if self.title:
                # Too many dots in filenames are not very handy, use underscores instead.
                # A matching suffix is appended automatically.
                self.filename = self.title
            else:
                raise SpecificationError, "<output>: either <filename> or 'id' attribute needed for format='%s'" \
                      % self.format

        self.have_shutdown = False

        return

    def shutdown(self, db):
        if not self.have_shutdown:
            for inp in self.inputs:
                drop_query_table(db, self.src_tables[inp])
                inp.shutdown(db)

            if self.gp:
                self.gp.close()
            
            self.have_shutdown = True
        return        
    
    def perform_query(self, db):
        if do_profiling():
            t0 = time.clock()

        for inp in self.inputs:
            inp.perform_query(db)

        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['perform_query'].append(t0)
        return

    def _build_pow2_tics(self, data):
        tics = []
        for i in data:
            tics.append('"%s" %d' %(build_pow2_label(i), i))
        # We limit the number of tic marks as to many tics are unreadable.
        max_idx = pb_max_idx_cnt
        rm_idx = len(tics) - 2
        while len(tics) > max_idx:
            tics.pop(rm_idx)
            rm_idx -= 2
            if rm_idx <= 0:
                rm_idx = len(tics) - 2

        return tics

    def _create_tics(self, data):
        """Try to be smart and create nice tics for the given data."""
        tics = []        
        # First try: for powers of two, create shorthands. Need
        # to check if all data is a power of two! Does only make
        # sense for integer data.
        idx = 0
        if len(data) > 0 and isinstance(data[idx], int):
            if data[idx] >= 0:
                i = data[idx]
                if i == 0:
                    if len(data) > 1:
                        idx += 1                    
                        i = data[idx]
                    else:
                        # special case: single '0' in the array
                        return tics

                # Check if all values are a power of 2
                while i > 1:
                    i /= 2
                if i == 1:
                    # First entry is a power of two, try the others!
                    is_power_of_2 = True
                    idx += 1
                    for idx2 in range(len(data[idx:])):
                        i2 = data[idx2]
                        while (i < i2):
                            i *= 2
                        if i != i2:
                            is_power_of_2 = False
                            break
                        i = i2
                    if is_power_of_2:
                        return self._build_pow2_tics(data)                    

        # For integer data, only integer labels makes sense. But gnuplot creates 1, 1.5, 2, 2.5, ...
        # But only do this for a reasonable number of tics! Otherwise, gnuplot will do a better job.
        if isinstance(data[idx], int):
            if data[-1]+1 - data[0] < 9:
                for idx in range(data[0], data[-1]+1):
                    tics.append(str(idx))
                return tics               
            
        # Replace multiples of 10^{+/- 3|6|9|12|...} with the respective prefix
        # XXX to be implemented

        # More smart tests to follow...        
        return tics
    
    def store_data(self, db):        
        """Plot all data into a single gnuplot chart."""
        global pb_label_sep
        
        if do_profiling():
            t0 = time.clock()

        crs = db.cursor()

        data_inputs = []  # those of input elements which actually provide data
        data_titles = {}  # the title of the data printed in the key
        label_elmts = {}  # concatenated parts of the labels, indexed by input
        r_info = {}
        x_unit = { 'top':None, 'bottom':None }
        y_unit = { 'left':None, 'right':None }
        for inp in self.inputs:
            inp.store_data(db)
            # check if any data has been stored
            sqlexe(crs, "SELECT count(%s) FROM %s" % (pb_dataidx_colname, self.src_tables[inp]))
            n_rows = crs.fetchone()[0]
            if n_rows == 0:
                continue
            data_inputs.append(inp)
            
            # check for updated result filter information
            for f in inp.update_filters():
                self.updated_filters.append(f)

                for ir in self.input_results[inp]:
                    if ir[6].count(pb_filter_str) > 0:
                        ir[6] = ir[6].replace(pb_filter_str, f[1], 1)
                        
                for flt in self.filters:
                    if flt.count(pb_filter_str) > 0:
                        # We can do this "blind" replacement because the parameters in the string
                        # and the updated filters are in the same order.
                        self.filters.remove(flt)
                        self.filters.append(flt.replace(pb_filter_str, f[1], 1))

            data_titles[inp] = ""            

            ri = self.input_results[inp][0]
            full_label = ri[6]
            r_info[inp] = []
            r_info[inp].extend(ri)
            if full_label:
                label_elmts[inp] = full_label.split(pb_label_sep)
                r_info[inp][6] = full_label.replace(pb_label_sep, '  ')

            # Assign axis' to the different inputs manually or automatically. If
            # a value to be plotted has different units in X or Y dimension, we want to
            # assign a different axis to it. Of course, this does only work for up to
            # two different units in each dimension.
            if self.inp_yaxis[inp] == "auto":
                for k in ('left', 'right', '#'):
                    if k == '#':
                        # No usable axis found! Need to abort.
                        raise SpecificationError, "<output> '%s': Found no available y-axis for '%s'" \
                              % (self.name, r_info[inp][1])
                    if y_unit[k] == r_info[inp][4] or y_unit[k] is None:
                        # use this same axis!
                        self.inp_yaxis[inp] = k
                        y_unit[k] = r_info[inp][4]
                        break                        
            else:
                if x_unit[self.inp_yaxis[inp]] is None:
                    x_unit[self.inp_yaxis[inp]] = r_info[inp][4]
                elif x_unit[self.inp_yaxis[inp]] != r_info[inp][4]:
                    if be_verbose():
                        print "#* WARNING: <output> '%s': plotting units '%s' and '%s' on the same x-axis!" \
                              % (self.name, x_unit[self.inp_yaxis[inp]], r_info[inp][4])

        # To unify the output filename, we append the filters passed up from the parameters.
        if self.fname_unify_mode == "filter":
            for f in self.filters:
                f = f.strip()
                f = f.replace("'", '')
                f = f.replace(' = ', '=')
                f = f.replace('  ', '_')
                f = f.replace(' ', '_')
                f = f.replace('/', 'p')

                for t in f.split(pb_label_sep):
                    if not t in self.fname_unify:
                        self.fname_unify.append(t)
        elif self.fname_unify_mode == "sweep":
            if self.sweep_alias is not None:
                for s in self.sweep_alias.itervalues():
                    self.fname_unify.append(s.split(pb_sweep_suffix)[1])
                
        # If no "filterstring" attribute was defined, but at least one parameter has a label
        # style "title", we simply append the labels to the title with a default format.
        has_title_lable = False
        for v in self.inp_label_type.itervalues():
            if v in ("title", "fulltitle"):
                has_title_lable = True
                break
                
        if (self.filterstring or has_title_lable) and len(label_elmts) > 0:
            title_labels = ""
            # First, we need to determine the input which has the largest number of label elements.
            # Not all inputs have the same number, and we would miss one if we just checked i.e. the
            # label elements of the first input.
            d_idx = 0
            max_len = 0
            for d in data_inputs:
                if len(label_elmts[d]) > max_len:
                    max_len = len(label_elmts[d])
                    d_idx = data_inputs.index(d)

            for i in range(len(label_elmts[data_inputs[d_idx]])):
                all_equal = True
                current_elmt = []

                ref_label = label_elmts[data_inputs[d_idx]][i]
                for j in range(0, len(data_inputs)):
                    try:
                        label_j = label_elmts[data_inputs[j]][i]
                    except IndexError:
                        # different number of filter labels for the different data inputs;
                        # just proceed as if the labels would not match (which is the case..)
                        label_j = ""
                    current_elmt.append(label_j)
                    if label_j != ref_label:
                        all_equal = False

                if all_equal:
                    title_labels += mk_enhanced_gp(ref_label.replace("'", '')) + ', '
                else:
                    for j in range(len(data_inputs)):
                        if len(current_elmt[j]) > 0:
                            data_titles[data_inputs[j]] += current_elmt[j] + ' '
            title_labels = title_labels[:-2]
            if self.filterstring:
                self.title = self.title.replace(self.filterstring, title_labels.strip())
                if be_verbose():
                    print "#* replacing '%s' in titlestring with filter conditions '%s'" % \
                          (self.filterstring, title_labels)
            else:
                if self.title is not None and len(self.title) > 0:
                    self.title += " (%s)" % title_labels
                else:
                    self.title = title_labels

        # We replace '.' by spaces. This is "necessary" because an XML-compliant ID
        # must not contain spaces (we use dots instead), but the title of a plot should
        # allow to have spaces.
        gp = gnuplot(self.title, self.plot_options, self.use_color)
        
        for inp in data_inputs:
            sqlexe(crs, "SELECT * FROM %s" % self.src_tables[inp])
            db_rows = crs.fetchall()
            idx_map = {}
            label_map = {}
            plot_elmts = 0
            max_x = 0
            
            n_results = len(self.input_results[inp])
            n_params  = len(self.input_params[inp])
            if len(self.input_params[inp]) > 0:
                p_info = self.input_params[inp][0]
            else:
                # no parameter data vector available!
                p_info = None

            for r_idx in range(0, n_results, self.inp_nbr_results[inp]):                               
                data = []
                axis_map = ('x', 'y', 'z')

                for i in range(self.inp_nbr_params[inp] + self.inp_nbr_results[inp]):
                    data.append([])

                # Add the parameter values...
                max_p = {}
                for p_idx in range(n_params):
                    for row in db_rows:
                        # offset '4' to skip index and data source columns
                        p_val = row[4 + p_idx]
                        if not axis_map[p_idx] in max_p:
                            max_p[axis_map[p_idx]] = p_val
                        elif p_val > max_p[axis_map[p_idx]]:
                            max_p[axis_map[p_idx]] = p_val
                        data[p_idx].append(p_val)
                        plot_elmts += 1

                # ... and the matching result values.
                for r in range(r_idx, r_idx + self.inp_nbr_results[inp]):
                    for row in db_rows:
                        # again, offset '4' to skip index and data source columns
                        data[n_params + r - r_idx].append(row[4 + n_params + r])
                        plot_elmts += 1

                # Try to create "smart" tics marks (index) for the x axis.
                idx_map = {}
                for p_idx in range(n_params):
                    axis_idx = self._create_tics(data[p_idx])
                    if len(axis_idx) > 0:
                        idx_map[axis_map[p_idx]] = axis_idx
                    elif self.logscale.has_key(axis_map[p_idx]) and self.logscale[axis_map[p_idx]] == 2:
                        # enfore log2-base labels in this case
                        log2 = []
                        for i in range(0,40):
                            tic = 2**i
                            if tic > max_p[axis_map[p_idx]]:
                                break
                            log2.append(2**i)
                        idx_map[axis_map[p_idx]] = self._build_pow2_tics(log2)
               
                if len(label_map) == 0:
                    # Use unit (& synopsis information) for axis labels
                    p_idx = 0
                    label_map['x'] = ""
                    for p_idx in range(n_params):
                        p_info = self.input_params[inp][p_idx]
                        label_map[axis_map[p_idx]] = p_info[5]
                        if not p_info[4] in ("none", ""):
                            label_map[axis_map[p_idx]] += " [" + p_info[4] + "]"
                    p_idx += 1
                    label_map[axis_map[p_idx]] = r_info[inp][5]
                    if not r_info[inp][4] in ("none", ""):
                        label_map[axis_map[p_idx]] += " [" + r_info[inp][4] + "]"

                data_title = self.inp_label_text[inp]
                lbl_type = self.inp_label_type[inp].strip()
                if not lbl_type in ('empty', 'value', 'full', 'parameter', 'input_id', \
                                    'explicit', 'fulltitle', 'title'):
                    print "#* WARNING: <output> '%s': invalid content '%s' for attribute 'label' in <input> '%s'\n" \
                          % (self.name, lbl_type, inp.get_name())
                if lbl_type == "title":
                    # Only put the parameters that change into the label string; others (which are
                    # constant) are appended to the title.
                    data_title += data_titles[inp]
                if lbl_type == "fulltitle":
                    data_title += r_info[inp][1]
                    if len(data_titles[inp]) > 0 and data_titles[inp] != ' ':
                        # ' ' is the dummy for a non-matching boolean filter
                        data_title += " for " + data_titles[inp]
                if lbl_type in ("value", "full"):
                    data_title += r_info[inp][1]
                if lbl_type in ("parameter", "full"):
                    if r_info[inp][6]:
                        if len(data_title) > 0:
                            data_title += " for "
                        data_title += r_info[inp][6]
                if lbl_type == "input_id":
                    data_title += inp.get_name().replace('.', ' ')
                    # remove possible trailing <sweep> markers
                    idx = data_title.find(pb_sweep_suffix)
                    if idx > 0:
                        data_title = data_title[:idx]                        
                if lbl_type == "explicit":
                    # already set to label_text
                    pass

                # pass additional options
                options = {}
                options['y-axis'] = self.inp_yaxis[inp]
                
                if plot_elmts > 0:
                    gp.set_data(data, idx_map, data_title, label_map, \
                                self.inp_plot_type[inp], self.inp_plot_style[inp], options)
                elif be_verbose():
                    print "#* WARNING: output '%s' has nothing to plot." % self.name

        for f in self.fname_unify:
            self.filename += '_' + f
            
        gp.plot(self.format, self.filename)

        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)
        return


