# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_operator - Implementation of the operators used in queries.
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
from pb_common import pb_debug
from pb_query_classes import *
import pb_source 

import xml
import re
from sys import exit
from string import lower, rstrip
from xml.etree import ElementTree
from math import *
import time


# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg

# Different operator types may be implemented with the same class. If new operators
# are added, a mapping from operator 'type' to the 'class' needs to be added here.
pb_map_optype_opclass = { 'avg':'stat', 'stddev':'stat', 'variance':'stat',
                          'median':'quantile', 'quantile':'quantile', 
                          'min':'minmax', 'max':'minmax',
                          'percentof':'rel', 'above':'rel', 'below':'rel',
                          'scale':'transform', 'offset':'transform', 'normalize':'transform',
                          'eval':'eval',
                          'null':'null',
                          'count':'count',
                          'diff':'pair', 'div':'pair',
                          'prod':'prod',
                          'sum':'sum',
                          'distrib':'distrib',
                          'sort':'sort',
                          'slice':'slice', 'oldest':'slice', 'latest':'slice',
                          'runindex':'runindex',
                          'param':'param',
                          'resolve':'resolve',
                          'limit':'filter', 'abslimit':'filter',
                          'round':'round',
                          'frequency':'frequency'
                          }

# New operators are based on the 'operator' base class. The name of the new operator is
# prefixed with the operator 'class', which is mapped from the operator 'type' via
# pb_map_optype_opclass.
# The operator base class provides generic functionality. More or less parts of this
# need to be overloaded by a new communicator.
# There are multiple sort of operators, differentiated by:
# - their ability to reduce a data vector into a single scalar (setting of 'self.can_reduce')
# - by the possible direct mapping of the operator to an SQL 'aggregation'. (setting of
#   self.is_sql_op)
# - the number of <input> elements that an operator needs to (or can) process (setting of
#   self.n_inputs)
#
# An operator with 'self.can_reduce == True' (which is the default) has to provide a
# reduce_vector() function if 'self.is_sql_op == False' (example: quantile_operator).
# Otherwise, the generic reduce_vector function is used, which in turn uses SQL to
# reduce a vector (example: stat_operator). The same is true for the function
# '_aggregate_dataset()' which is only called for an operator with 'self.can_reduce == True'
# and 'self.is_sql_op == False' when multiple result values for the same parameter set
# have to be reduced into a single value.
#
# The function _calculate() needs to be provided by all operators that can not reduce and
# by those which can process more than one <input>s. It is used to 

class operator(data):
    """This class performs operations on single or multiple data vectors and delivers the
    resulting datasets. If a single source is specified, the operation will be performed
    for each result value on the data sets with identical parameter value sets (i.e., to
    generate the average of a result value across multiple runs). If more than one source
    is specified, the operation will be applied to the individual result values of the
    data sources (i.e., to build the difference of the (average) timings of two different
    programm versions)."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        global pb_all_ids, pb_sweep_suffix, pb_namesrc_sep

        data.__init__(self, elmnt_tree, all_nodes, db)

        self.all_nodes = all_nodes
        self.have_performed_query = False
        # This operator *can* reduce multiple values into one.
        self.can_reduce = True 
        # This operator has no direct SQL equivalent. Only relevant if can_reduce == True
        self.is_sql_op = False 
        # When aggregating data from multiple runs, the resulting value stems from one of
        # the runs (like 'min'). Set to False if the resulting value is calculated from all
        # other values (like 'avg').
        self.exact_aggregate = True
        self.scope = "global"
        
        self.have_stored_data = []
        self.value = None
        self.updated_filters = []
        self.scalar_var = {}
        self.scalar_var_content = {}
        self.scalar_map = {}
        
        self.valid_input = [ "operator", "source", "combiner" ]
        self.type = "operator"

        self.name = elmnt_tree.get('id')
        if not self.name:
            raise SpecificationError, "each <operator> needs to have a 'id' attribute"

        self.op_type = "null"
        self.op_type = elmnt_tree.get('type')

        self.match_type = get_attribute(elmnt_tree, "<operator> %s" % self.name, "match", "parameter",
                                        [ "parameter", "index", "modulo" ])
        
        if sweep_alias != None:
            # Build a new name by appending the sweep suffixes of the underlying
            # sources/operators in an *ordered* manner. This means, the source with the
            # suffix '~2' uses the third (0.1,2) variation of the parameter. This
            # allows to group sources by their parameter variations just by grouping
            # sources with the same sweep index.
            # If multiple sweep parameters do exist, their suffixes are concanated by
            # dots ('.').
            self.name += pb_sweep_suffix
            for v in sweep_alias.itervalues():
                self.name += sweep_idx(v) + '.'
            self.name = self.name[:-1]

        if do_debug():
            print "#* DEBUG: Initializing operator of type '%s'" % self.op_type

        # Check all data sources (either a source or another operator) that have been provided
        inp_nodes = elmnt_tree.findall('input')
        if not inp_nodes:
            raise SpecificationError, "<operator> '%s': need at least one <input> tag" % self.name
        self.sources = {}
        self.input_names = []
        self.src_alias = {}
        self.inp_label_type = {}
        self.inp_label_text = {}
        for inp in inp_nodes:
            inp_name = inp.text
            if sweep_alias != None and sweep_alias.has_key(inp_name):
                inp_name = sweep_alias[inp_name]
            if not all_nodes.has_key(inp_name):
                raise SpecificationError, "<operator> '%s': <input> '%s' is not defined" % (self.name, inp_name)
            if not pb_all_ids[base_id(inp_name)] in self.valid_input:
                raise SpecificationError, "<operator> '%s': invalid <input> '%s' (needs to be <source>, <operator> or <combiner>)" % \
                      (self.name, inp_name)
            if do_debug():
                print "#* DEBUG: adding input '%s'" % inp_name
            self.inp_label_type[inp_name] = inp.get("label")
            if self.inp_label_type[inp_name] is None:
                self.inp_label_type[inp_name] = "auto"
            self.inp_label_text[inp_name] = mk_label(inp.get("labeltext"), all_nodes)
            if self.inp_label_text[inp_name] is None:
                self.inp_label_text[inp_name] = ""
                
            self.input_names.append(inp_name)
            self.sources[inp_name] = all_nodes[inp_name]

            alias = mk_label(inp.get('alias'), all_nodes)
            if alias:
                self.src_alias[alias] = inp_name

        # Make sure that we have a matching number of result values for the
        # demanded operation type.
        if self.n_inputs != 0 and len(self.input_names) != self.n_inputs:
            raise SpecificationError, "<operator> '%s': operation '%s' needs %d instead of %d data sources" % \
                  (self.name, self.op_type, self.n_inputs, len(self.input_names))
        # In case of multiple data sources, make sure that the result values
        # of those do match.
        n_results = -1
        for n in self.input_names:
            r = len(self.sources[n].get_result_info())
            if n_results == -1:
                n_results = r
                continue
            if n_results != r:
                raise SpecificationError, "<operator> '%s': inputs have different numbers of result values" % \
                      self.name
                
        # Determine the data that we get from the data sources, and which one we will pass up.
        self.value_src_map = {}
        self.param_infos = []
        self.src_result_infos = []
        for n in self.input_names:
            src_params = self.sources[n].get_param_info()
            for s in src_params:
                if self.param_infos.count(s) == 0:
                    self.param_infos.append(s)
                    self.value_src_map[mk_info_key(s)] = n

            src_results = self.sources[n].get_result_info()
            for s in src_results:
                if self.src_result_infos.count(s) == 0:
                    self.src_result_infos.append(s)
                    self.value_src_map[mk_info_key(s)] = n

        if do_debug():
            print "#* DEBUG: <operator> %s:" % self.name
            print "   params :", self.param_infos
            print "   results:", self.src_result_infos
            
        if len(self.param_infos) == 0 and sweep_alias == None and self.need_params:
            # We might also end here if all parameters are <sweep> parameters as they don't
            # show up in self.param_infos. There's not much that can be done about it for now...
            raise SpecificationError, "<operator> '%s': no parameter specified which provides data vectors (use a <series>!)" % \
                  self.name

        # Data from the sources will be stored here for further operating
        # Only add columns to the output table which actually are
        # provided by each source!
        self.src_tables = {}
        for n in self.input_names:
            self.src_tables[n] = self.sources[n].get_table_name()

        self.have_shutdown = False
        return
    
    def shutdown(self, db):
        """Clean up & shutdown"""
        if not self.have_shutdown:
            for n in self.input_names:
                self.sources[n].shutdown(db)
            drop_query_table(db, self.tgt_table)
            self.have_shutdown = True
        return

    def perform_query(self, db):
        """Let all data sources perform the queries on the experiment database"""
        if do_profiling():
            t0 = time.clock()
            
        if not self.have_performed_query:
            self.have_performed_query = True

            for n in self.input_names:
                # TODO: launch a new thread here to execute this loop iteration,
                # continue with the next iteration, and wait for all threads 
                # after the loop.
                self.sources[n].perform_query(db)
                # check for updated result filter information
                for f in self.sources[n].update_filters():
                    self.updated_filters.append(f)
                    new_ris = []
                    for ri in self.result_infos:
                        if ri[6].count(f[0]) > 0:
                            new_ris.append((ri, (ri[0], ri[1], ri[2], ri[3], ri[4], ri[5],
                                                 ri[6].replace(f[0], f[1]))))
                    for ri in new_ris:
                        self.result_infos.remove(ri[0])
                        self.result_infos.append(ri[1])

        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['perform_query'].append(t0)
        return

    def _get_result_name(self, result_infos):
        """Provide a name for the result value(s) of this operator when this name is to be
        constructed automatically. New operators might overload this function. It is only called
        from _build_result_info()."""
        new_name = self.op_type + "("
        for ri in result_infos:
            new_name += ri[1] + ","
        return new_name[:-1] + ')'

    def _match_filters(self, result_idx):
        """Make sure that only the parameters are passed up which actually apply to *both*
        <input>s - otherwise, irritating or wrong statements about the applied parameter
        filters may be printed. This requires that the parameter filter settings for
        both inputs are matched, but this is usually the case anyway, no problem to do and
        useful to make sure you don't compare apples with oranges."""    
        new_filter=""

        filters={}
        for inp in self.input_names:
            filters[inp] = self.sources[inp].get_result_info()[result_idx][6]
        for f in filters[inp].split(pb_label_sep):
            add_filter = True
            for v in filters.itervalues():
                vv = v.split(pb_label_sep)
                if f not in vv:
                    add_filter = False
                    break
            if add_filter:
                new_filter += f+pb_label_sep
        if len(new_filter) > 0:
            new_filter = new_filter[:-len(pb_label_sep)]

        return new_filter

    def _build_result_info(self, result_type = None):
        """Build a meaningful name for the result value(s) of this
        operator within the result_info structure to be created.

        This standard implementation works for many operators. If only
        the name in the new result_info is constructed differently, it
        will suffice to overload _get_result_name. However, some
        operators need to do special things and will then overload
        _build_result_info() itself."""
        
        self.result_infos = []

        if len(self.input_names) == 1:
            # Aggregate the single result values from the source (which typically
            # provides data from multiple runs!), or reduce the output vector(s) of
            # an operator into a single data set.
            # Operator 'count' gives the number of runs that contribute to each data set.
            for ri in self.src_result_infos:
                lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
                if  lbl_type == "auto":
                    new_name = self._get_result_name([ri])
                elif lbl_type == "empty":
                    new_name = ""
                elif lbl_type == "ignore":
                    new_name = ri[1]
                elif lbl_type == "parameter":
                    new_name = ""                     
                elif lbl_type == "explicit":                
                    new_name = self.inp_label_text[self.input_names[0]]
                else:
                    if be_verbose():
                        print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                    new_name = "???"

                ri_new = []
                ri_new.extend(ri)
                ri_new[1] = new_name
                if result_type is not None:
                    ri_new[2] = result_type
                    ri_new[3] = pb_valid_dtypes[result_type]
                
                self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
                self.result_infos.append(ri_new)
        else:
            # Operate on multiple result values from multiple data sources
            # by matching them ordered.
            for r in range(len(self.sources[self.input_names[0]].get_result_info())):
                lbl_type = self.inp_label_type[self.input_names[0]]
                if  lbl_type == "auto":
                    r_infos = []
                    ri_prev = None
                    for sn in self.input_names:
                        # Need to check if the result values are of the same type.
                        # Ideally, we would also check the unit. To be done!
                        ri = (self.sources[sn].get_result_info())[r]
                        r_infos.append(ri)
                        if ri_prev and ri[2][:4] != ri_prev[2][:4]:
                            raise SpecificationError, "<operator> '%s': non-matching result values" % self.name
                        ri_prev = ri
                    new_name = self._get_result_name(r_infos)
                elif lbl_type == "empty":
                    new_name = ""
                elif lbl_type == "ignore":
                    ri = (self.sources[self.input_names[0]].get_result_info())[r]
                    new_name = ri[1]
                elif lbl_type == "parameter":
                    new_name = ""                     
                elif lbl_type == "explicit":                
                    new_name = self.inp_label_text[self.input_names[0]]
                else:
                    if be_verbose():
                        print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                    new_name = "???"

                ri_new = []
                ri_new.extend(ri)
                ri_new[1] = new_name
                if result_type is not None:
                    ri_new[2] = result_type
                    ri_new[3] = pb_valid_dtypes[result_type]

                self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
                self.result_infos.append(ri_new)

        return

    def _setup_target_table(self, db):
        """Set up target table for output."""
        table_entries = []
        for j in (self.param_infos, self.result_infos):
            for i in j:
                table_entries.append((i[0], i[3]))
        try:
            self.tgt_table = create_query_table(db, table_entries)
        except SpecificationError, error_msg:
            print "#* ERROR: could not set up target table"
            print "  ", error_msg
            exit(1)
                
        return
    
    def _build_param_sets(self, db, table_name):
        """Build the sets of parameters by which the operator queries are performed.
        These lists can become quiet large, depending on the number N_p of parameters
        and the number of distinct values V_d(p) that each parameter p has! General
        formula is: product over all V_d(p), 0 < p < N_p."""
        crs = db.cursor()

        # For each parameter value provided by the source, retrieve the
        # set of distinct contents.
        param_vals = {}
        param_idx = {}
        for p in self.param_infos:
            v_name = p[0]
            param_vals[v_name] = []
            param_idx[v_name] = 0

            sqlexe(crs, "SELECT DISTINCT %s FROM %s" % (v_name, table_name),
                   "#* DEBUG: _build_param_sets, distinct content query:")
            db_rows = crs.fetchall()
            for row in db_rows:
                param_vals[v_name].append(row[0])

        # Build the list of all possible pairings
        all_sets = []
        all_p_names = []
        loop_cnt = 1
        for p in self.param_infos:
            all_p_names.append(p[0])
            loop_cnt *= len(param_vals[p[0]])

        for i in range(loop_cnt):
            value_set = []
            for j in range(len(all_p_names)):
                value_set.append(param_vals[all_p_names[j]][param_idx[all_p_names[j]]])
            all_sets.append(value_set)

            for j in range(len(all_p_names)):
                param_idx[all_p_names[j]] += 1
                if param_idx[all_p_names[j]] == len(param_vals[all_p_names[j]]):
                    param_idx[all_p_names[j]] = 0
                else:
                    break
                
        if do_debug():
            print "#* all sets of parameters for operation:"
            print all_sets
        # The tupels (sub-arrays) in the returned list are ordered in the same way
        # as the parameter names in self.param_infos ("for p in self.param_infos: ...")
        return all_sets

    def _aggregate_dataset(self, results):
        """For operations which are not performed via SQL, this function has to be used. The
        dataset is a list which contains the result values of the matching datasets. The
        operator has to aggregate (reduce) them to a single value. It has to return a string
        which can be used within an SQL statement to update an element."""
        return None

    def _aggregate_runs(self, db, table_name = None):
        """Aggregate single result values across multiple runs."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]       
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name
        param_sets = self._build_param_sets(db, op_tbl)

        for p_set_idx in range(len(param_sets)):
            # First, create a new row in the output table for this parameter set.
            col_str = pb_origin_colname + ","
            val_str = "'" + self.name + "',"
            for p_idx in range(len(self.param_infos)):
                col_str += self.param_infos[p_idx][0] + ","
                val_str += get_sql_contents(self.param_infos[p_idx],
                                            param_sets[p_set_idx][p_idx]) + ","
            col_str = col_str[:-1]
            val_str = val_str[:-1]
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, val_str),
                   "#* DEBUG: creating new data set (paramters):" )
                
            # Now, aggregate all data sets with identical parameter sets, and store
            # the result in the output table.            
            for r_i in self.result_infos:
                # For each result value requested, we have to aggregate separately
                p_condition = ""
                for p_idx in range(len(self.param_infos)):
                    p_condition += " %s=%s AND" % (self.param_infos[p_idx][0],
                                                   get_sql_contents(self.param_infos[p_idx],
                                                                    param_sets[p_set_idx][p_idx]))                    
                p_condition = rstrip(p_condition, "AND")
                if len(p_condition) > 0:
                    p_condition = "WHERE %s" % p_condition
                    
                if be_verbose():
                    # This information is interesting to check the validity of the generated data. Can also
                    # be achieved via the count operator.
                    sqlexe(crs, "SELECT %s,%s,%s FROM %s %s" % (r_i[0], pb_runidx_colname, pb_runorder_colname,
                                                                op_tbl, p_condition))
                    print " #* operator '%s' performs %s() on %d probes" % (self.name, self.op_type, crs.rowcount)
                if self.is_sql_op:
                    sql_cmd = "SELECT %s(%s) FROM %s %s" % (self.op_type, r_i[0], op_tbl, p_condition)
                else:
                    sql_cmd = "SELECT %s,%s,%s FROM %s %s" % (r_i[0], pb_runidx_colname, pb_runorder_colname,
                                                              op_tbl, p_condition)
                sqlexe(crs, sql_cmd, "#* DEBUG: aggregating datasets with %s operator:" % self.op_type)

                # Store the parameter/result value set in the output table. For the 'count' operator,
                # store the number of "hits" intead.
                db_rows = crs.fetchall()
                if crs.rowcount == 0:
                    # No data - how comes?
                    if be_verbose():
                        print "#* WARNING: <operator> '%s' returned no data (operator type not applicable?)" % self.name
                    if self.op_type == "count":
                        # Make sure to deliver a 0 value (and not "None") if a count
                        # is applied on an empty result. No run index or order can be preserved in
                        # this case as it is not at "exact aggregation" (like min() would be).
                        # CHECK: is this required for other operators as well?
                        run_idx = -1
                        run_order = -1
                        data_str = "0"
                        sqlexe(crs, "UPDATE %s SET %s='%s',%s=%s,%s=%s %s" % (output_table, r_i[0], data_str,
                                                                              pb_runidx_colname, run_idx,
                                                                              pb_runorder_colname, run_order,
                                                                              p_condition),
                               "#* DEBUG: updating data set with:")
                elif db_rows[0][0] == None:
                    # This may happen if i.e. stddev() is run for a single data set
                    if be_verbose():
                        print "#* WARNING: <operator> '%s' returned 'None' (operator type not applicable?)" % self.name
                else:
                    if self.is_sql_op:
                        data_str = get_sql_contents(r_i, db_rows[0][0])

                        # We want to keep the relation of the run indexes with the data which is not
                        # directly possible when using SQL-based aggregation. In this case, we need to perform an
                        # additional query to determine the missing data. However, this is only applicable to
                        # operators which reduce to one exact value of one run - i.e., 'avg' creates a new
                        # value which is not contained in any run. In such a case, we can only set the run
                        # information to the 'invalid' mark.
                        if self.exact_aggregate:
                            if len(p_condition) > 0:
                                exact_cond = p_condition + " AND" 
                            else:
                                exact_cond = "WHERE"
                            sqlexe(crs, "SELECT %s,%s FROM %s %s %s=%s" % (pb_runidx_colname, pb_runorder_colname,
                                                                           op_tbl, exact_cond, r_i[0], data_str),
                                   "#* DEBUG: determining %s:" % self.op_type)
                            # This can deliver more than one row - which one should be taken in this case?!
                            if crs.rowcount > 1 and be_verbose():
                                print "#* WARNING: more than one row satisfies reduction condition!"
                            db_row = crs.fetchone()
                            run_idx = db_row[0]
                            run_order = db_row[1]
                    else:
                        dataset_elmts = []
                        for row in db_rows:
                            dataset_elmts.append(row[0])
                        data_str = self._aggregate_dataset(dataset_elmts)

                        if self.exact_aggregate:
                            run_idx = db_rows[0][1]
                            run_order = db_rows[0][2]

                    if not self.exact_aggregate:
                            run_idx = -1
                            run_order = -1

                    sqlexe(crs, "UPDATE %s SET %s='%s',%s=%s,%s=%s %s" % (output_table, r_i[0], data_str,
                                                                        pb_runidx_colname, run_idx,
                                                                        pb_runorder_colname, run_order,
                                                                        p_condition),
                           "#* DEBUG: updating data set with:")
                        
        crs.close()
        return

    def _reduce_vector(self, db, table_name = None):
        """Reduce a single vector of result values into a scalar value. For some
        operation types (min, max) it is possible to associate a parameter (set) to the
        scalar. For other operations (avg, stddev, prod, sum, variance), only the scalar
        result value has a meaning.

        'db' is the database connection to store the results."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        for r_i in self.result_infos:
            # For each result value requested, we have to aggregate separately
            if self.scope == "run":
                # We need to get all available 'run order index' value; a separate reduction will
                # be performed for each run.
                sqlexe(crs, "SELECT DISTINCT %s FROM %s" % (pb_runorder_colname, op_tbl))
                order_idx = get_crs_column(crs, 0)               
            else:
                order_idx = [-1]
            
            for run_idx in order_idx:
                if run_idx < 0:
                    sqlexe(crs, "SELECT %s(%s) FROM %s" % (self.op_type, r_i[0], op_tbl),
                           "#* DEBUG: reducing global data vector with %s operator:" % self.op_type)
                else:
                    sqlexe(crs, "SELECT %s(%s) FROM %s WHERE %s=%s" % (self.op_type, r_i[0], op_tbl, pb_runorder_colname, run_idx),
                           "#* DEBUG: reducing run-local data vector with %s operator:" % self.op_type)

                # Store the parameter/result value set in the output table
                db_rows = crs.fetchall()
                if db_rows[0][0] == None:
                    # This may happen if stddev() is run for a single data set
                    if be_verbose():
                        print "#* WARNING: operator '%s' returned no data (operator not applicable?)" % self.op_type
                else:
                    new_val = db_rows[0][0]

                    # We want to keep the relation of the run indexes with the data which is not
                    # directly possible when using SQL-based aggregation. In this case, we need to perform an
                    # additional query to determine the missing data.
                    sqlexe(crs, "SELECT %s,%s FROM %s WHERE %s=%s" % (pb_runidx_colname, pb_runorder_colname,
                                                                      op_tbl, r_i[0], new_val),
                           "#* DEBUG: getting run index and order")
                    # This can deliver more than one row - which one should be taken in this case?!
                    if crs.rowcount > 1 and be_verbose():
                        print "#* WARNING: more than one row satisfies reduction condition!"
                    db_row = crs.fetchone()
                    if db_row is None:
                        # For operations like stddev or avg, the previous SELECT will not
                        # return any data because "new_val" is not contained in the query table
                        run_idx = -1
                        run_order = -1
                    else:
                        run_idx = db_row[0]
                        run_order = db_row[1]

                    sqlexe(crs, "INSERT INTO %s (%s,%s,%s) VALUES (%s,%s,%s)" % (output_table, r_i[0], pb_runidx_colname,
                                                                                 pb_runorder_colname, new_val, run_idx,
                                                                                 run_order),
                           "#* DEBUG: updating data vector with:")
        
        db.commit()
        return            

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        return None
                
    def _operate(self, db, table_name = None):
        """Perform operation on result values from different data sources."""
        crs = db.cursor()
        # Build a query which operates on all the (different) columns in the
        # tables filled by the data sources.
        # We select the data sets of both tables which have identical parameters,
        # and insert this result in the output table. This is a very simple approach,
        # but should be o.k. for now. 

        row_select_str = " WHERE "
        # CHECK: Is it necessary to match the values not only by the parameter values, but
        # also by the row idx? If we do match the row index, we run into problems when
        # the different data sets have not identical parameter value vectors. Which problems
        # do we may get when *not* matching the row index? Can't think of any.
        #for n in self.input_names:
        #    row_select_str += self.src_tables[n] + '.' + pb_dataidx_colname + '='
        #row_select_str = rstrip(row_select_str, '=') + " AND "
        select_params = []
        select_idx = 0
        if self.match_type == "parameter":
            for pi in self.param_infos:
                i = 0
                for n in self.input_names:
                    # Need to differentiate between a scalar variable (for which the content is
                    # fetched only once, and this is done here); and the "normal" vector parameters
                    # which are fetched from the tables. The problem is that we need to skip the
                    # scalar variables in the "vector queries".
                    if self.scalar_var.has_key(n):
                        # need to get content for this value only once
                        if not self.scalar_var_content.has_key(n):
                            sqlexe(crs, "SELECT "+self.scalar_var[n]+" FROM "+self.src_tables[n],
                                   "#* DEBUG: get single value via:")
                            if crs.rowcount != 1:
                                raise DataError, "scalar variable '%s' needs to return exactly one value!" % n
                            self.scalar_var_content[n] = crs.fetchone()[0]
                    else:
                        row_select_str += self.src_tables[n] + '.' + pi[0] + '='
                        select_idx = i
                        if i == 0:
                            # We need to get each parameter only once (from one source table)
                            # as we make sure that they are identical anyway (via 'row_select_str)!
                            select_params.append(pi)                        
                    i += 1
                row_select_str = rstrip(row_select_str, '=') + " AND "

            row_select_str = rstrip(row_select_str, " AND ")
        elif self.match_type == "index":
            i = 0
            for n in self.input_names:
                row_select_str += self.src_tables[n] + '.' + pb_dataidx_colname + '='
                select_idx = i
                i += 1
            # Here, we can not be sure if all parameters from the matched datasets are
            # identically. They *SHOULD* be, otherwise the query might not make sense. But
            # the user is responsible for this. Anyway, we can only show *one* parameter,
            # thus we just take the ones from the first source.
            select_params.extend(self.param_infos)                        
            row_select_str = rstrip(row_select_str, '=')
        elif self.match_type == "modulo":
            # Do a modulo (round-robin) pairing between indexes. This mode allows to match paramter
            # vectors with different lengths, esp. one vector with length > 1 and one with length == 1.
            # For this, we first need to determine the vector with longer length, and do the modulo
            # operation on this parameters dataidx column.
            if len(self.input_names) != 2:
                raise SpecificationError, "'modulo' matching does require exactly two <input>s (have %d)" % len(self.input_names)
            max_cnt = 0
            max_inp = None
            col_cnt = {}
            for n in self.input_names:
                sqlexe(crs, "SELECT count(*) FROM "+self.src_tables[n], None)
                col_cnt[n] = crs.fetchone()[0]
                if col_cnt[n] == 0:
                    raise DataError, "parameter needs to have at least one content for 'modulo' matching"
                if col_cnt[n] > max_cnt:
                    max_cnt_inp = n
                    max_cnt = col_cnt[n]
                sqlexe(crs, "SELECT _pb_data_idx_ FROM "+self.src_tables[n], None)
                print self.src_tables[n], crs.fetchall()
            min_cnt_inp = self.input_names[1-self.input_names.index(max_cnt_inp)]
            idx_col = pb_dataidx_colname
            select_params.extend(self.param_infos)
            row_select_str += "(%s.%s %%%% %d = %s.%s)" % (self.src_tables[max_cnt_inp], idx_col, col_cnt[min_cnt_inp],
                                                         self.src_tables[min_cnt_inp], idx_col)
            
        # Fill up the output table with the parameter sets. Assuming that each
        # input table contains the same set of parameters, it is sufficient to
        # only use the parameter sets of one table when making sure that identical
        # sets do also exist in the other table(s).
        if len(select_params) > 0:
            sql_cmd = "SELECT "
            for pi in select_params:
                sql_cmd += self.src_tables[self.input_names[select_idx]] + '.' + pi[0] + ','
            sql_cmd = sql_cmd[:-1] + " FROM "
            for t in self.src_tables.itervalues():
                sql_cmd += t + ","
            sql_cmd = sql_cmd[:-1]
            # We only need a "WHERE" filter if it actually serves to match rows from multiple tables.
            # The entries in 'select_params' may actually
            # refer to the same parameter within different tables, so it might be sufficient to check just
            # for 'len(select_params) > 1'!?
            if row_select_str.find('=') > 0:
                sql_cmd += row_select_str
            if do_debug():
                print self.param_infos
                print self.input_names
            sqlexe(crs, sql_cmd, "#* DEBUG: _operate() [%s]: SQL for param select:" % self.name)
        else:
            # No parameter sets could be created -  this means all available values should be chosen!
            # In this case, we have the problem that we can not match the individual elements of the
            # input vectors by any of their parameters (as there are none). However, this can still
            # make sense in two cases: 
            # 1. The input vectors get sorted and elemetns are implicitely matched by the sort order
            # 2. The input vecors both only have a single element (are scalars, effetively)
            # We check for this below.
            sqlexe(crs, "SELECT * FROM %s" % (self.src_tables[self.input_names[0]]),
                   "#* DEBUG: _operate() [%s]: SQL for all-data select:" % (self.name))

        if crs.rowcount == 0:
            # No parameters match - return empty output table!?
            if be_verbose() or do_debug():
                print "#* _operate(): No matching parameter sets."
            return
        db_rows = crs.fetchall()
        if len(select_params) == 0 and len(self.input_names) > 1:
            if len(db_rows) > 1 and be_verbose():
                # TODO: we can not (yet) verify whether data is sorted or not.
                print "#* WARNING <operator %s>: no parameter data vector - matching not possible." \
                    % (self.name, )

        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        col_str = pb_origin_colname + ','
        for pi in self.param_infos:
            col_str += pi[0] + ','
        col_str = col_str[:-1]
        
        for row in db_rows:
            val_str = "'" + self.name  + "',"
            for i in range(len(self.param_infos)):
                val_str += get_sql_contents(self.param_infos[i], row[i]) + ','
            val_str = val_str[:-1]
            try:
                sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, val_str),
                       "#* DEBUG: _operate(): SQL for param insert:")
            except psycopg.ProgrammingError, error_msg:
                print "#* ERROR: Illegal SQL query:", error_msg
                exit(1)

        # Now, for each result value, update the respective row in the output table.
        for idx in range(len(self.result_infos)):
            op_rows = self._calculate(crs, idx, row_select_str)
            if op_rows == None:
                continue

            # Insert the results of the operation into the ouptut table
            row_idx = 1
            for row in op_rows:
                # row format: [run_idx, run_order, data]
                run_idx_str = ""
                if row[0] is not None:
                    run_idx_str = ",%s=%d" % (pb_runidx_colname, row[0])
                run_order_str = ""
                if row[1] is not None:
                    run_order_str = ",%s=%d" % (pb_runorder_colname, row[1])
                if row[2] is not None:
                    sqlexe(crs, "UPDATE %s SET %s=%s%s%s WHERE %s=%d" % (output_table,
                                                                         (self.result_infos[idx])[0],
                                                                         get_sql_contents(self.result_infos[idx],
                                                                                          row[2]),
                                                                         run_idx_str,
                                                                         run_order_str,
                                                                         pb_dataidx_colname, row_idx),
                           "#* DEBUG: _operate(): SQL for result insertion:")
                row_idx += 1

        # Perform the transaction
        db.commit()           
        return

    def store_data(self, db, table_name = None):
        """Get data from the data sources, process it, and store it in the ouput table"""
        if do_profiling():
            t0 = time.clock()

        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        if output_table in self.have_stored_data:
            if do_profiling():
                t0 = time.clock() - t0
                self.prof_data['store_data'].append(t0)
            return
        self.have_stored_data.append(output_table)

        if do_debug():
            print "#* DEBUG: store_data of <operator> %s in table %s" % (self.name, output_table)
          
        crs = db.cursor()

        for n in self.input_names:
            # TODO: run each iteration of this loop as a new thread, and wait for them 
            # after the loop.
            self.sources[n].store_data(db)

        if len(self.input_names) > 1 or not self.can_reduce:
            # Relate the matching datasets from multiple inputs, or operate on each
            # input's data vector if the operator can not reduce.
            if do_debug():
                print "#* DEBUG: operating on sources:"
                for n in self.input_names:
                    print "  %s" % n
            self._operate(db, output_table)
        else:
            if pb_all_ids[base_id(self.input_names[0])] == "source":
                # Aggregate data from multiple runs.
                if self.scope == "global":
                    if do_debug():
                        print "#* DEBUG: globally aggregate source %s" % (self.input_names[0])
                    self._aggregate_runs(db, output_table)
                elif self.scope == "run":
                    if do_debug():
                        print "#* DEBUG: aggregate source %s run-by-run" % (self.input_names[0])
                    self._reduce_vector(db, output_table)
            else:
                # This operator has another operator provide the input data. This means we
                # do not aggregate data from multiple runs into one, but instead reduce the
                # vector(s) of data into a single value.
                if do_debug():
                    print "#* DEBUG: reducing operator ouput %s" % (self.input_names[0])
                self._reduce_vector(db, output_table)

        crs.close()
        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)
        return
    
    def get_param_info(self):
        return self.param_infos

    def get_next_paramset(self):
        return

    def get_result_info(self):
        return self.result_infos
    
    def update_filters(self):
        return self.updated_filters

    def get_next_resultset(self):
        return      


class null_operator(operator):
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 0  # number of inputs required (0 means unlimited)
        self.need_params = False   # does not care for parameter data vectors
        
        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self._build_result_info()
        self._setup_target_table(db)

        self.can_reduce = False   

        return

    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""       
        # We simply pass all data through, but avoid create duplicate columns in the
        # output table. Up to now, we just don't add a value which does already exist
        # which is a little bit simplistic. Instead, we should also check i.e. if we
        # should clear the filter string if it differs between the values etc. On the
        # other hand, the user should know what he is doing in this case...
        used_names = {}
        self.result_infos = []        
        for ri in self.src_result_infos:
            if not used_names.has_key(ri[0]):
                self.result_infos.append(ri)
                used_names[ri[0]] = True

        return

    def store_data(self, db, table_name = None):
        """Get data from the data sources, process it, and store it in the ouput table"""
        if do_profiling():
            t0 = time.clock()

        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        if output_table in self.have_stored_data:
            if do_profiling():
                t0 = time.clock() - t0
                self.prof_data['store_data'].append(t0)
            return
        self.have_stored_data.append(output_table)

        if do_debug():
            print "#* DEBUG: store_data of <operator> %s" % self.name
            print self.tgt_table, self.src_tables

        # Special case: let the data sources store their data directly into the output table.
        for n in self.input_names:
            self.sources[n].store_data(db, output_table)
            
        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)

        return
    

#
# derived operators (with actual functionality beyond "null")
#

class stat_operator(operator):
    """Used for avg, stddev, variance"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # This operator can operate on a result vector alone. 

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self.scope = get_attribute(elmnt_tree, "<operator> %s" % self.name, "scope",
                                   'global', ['run', 'global'])

        self._build_result_info("float")
        
        self.is_sql_op = True
        self.exact_aggregate = False
        
        # Check for a special case: if we are reducing an input vector from another
        # operator with an operation different from min() or max() (or one of these
        # aggregators with more than one result value), no parameter values can be provided!
        # CHECK: This is a problem in some situations - need to take a closer look at this!
        if (len(self.input_names) == 1 and isinstance(self.sources[self.input_names[0]], operator)):
            self.param_infos = []

        self._setup_target_table(db)
        return
        

class round_operator(operator):
    """Used for round"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self._build_result_info()
        self._setup_target_table(db)        

        self.is_sql_op = False        
        self.exact_aggregate = False
        # We do the same things as if we would reduce (treat a single input vector)
        self.can_reduce = True

        self.precision = 3
        att = mk_label(elmnt_tree.get('value'), all_nodes)
        if att is not None:
            try:
                self.precision = int(att)
            except ValueError:
                raise SpecificationError, "<operator> %s: invalid content '%s' 'value' attribute (has to be integer)" \
                      % (self.name, self.round)
        
        return

    def _reduce_vector(self, db, table_name = None):
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        for r_i in self.result_infos:
            # For each result value requested, we have to aggregate separately
            val_str = "%s(CAST(%s AS NUMERIC),%d),%s,%s,%s," % (self.op_type, r_i[0], self.precision,
                                                                pb_origin_colname, pb_runidx_colname,
                                                                pb_runorder_colname)
            for p_i in self.param_infos:
                val_str += "%s," % p_i[0]
            val_str = val_str[:-1]
                
            sqlexe(crs, "SELECT %s FROM %s" % (val_str, op_tbl),
                   "#* DEBUG: processing data vector with %s operator:")
            nim = build_name_idx_map(crs)

            # Store the parameter/result values set in the output table
            val_str = "%s,%s,%s,%s," % (r_i[0],  pb_origin_colname, pb_runidx_colname, pb_runorder_colname)
            for p_i in self.param_infos:
                val_str += "%s," % p_i[0]
            val_str = val_str[:-1]

            db_rows = crs.fetchall()
            for row in db_rows:
                data_str = "%s,'%s',%s,%s," % (row[0], row[1], row[2], row[3])
                for p_i in self.param_infos:
                    data_str += get_sql_contents(p_i, row[nim[p_i[0].lower()]]) + ","
                data_str = data_str[:-1]
                
                sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, val_str, data_str),
                       "#* DEBUG: inserting result data")
        
        db.commit()
        return            


class quantile_operator(operator):
    """Used for median and quantile"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self.scope = get_attribute(elmnt_tree, "<operator> %s" % self.name, "scope",
                                   'global', ['run', 'global'])        

        self.is_sql_op = False
        self.exact_aggregate = False
        
        if self.op_type == 'median':
            self.value = 50.0

        att = mk_label(elmnt_tree.get('value'), all_nodes)
        if att != None:
            try:
                if all_nodes.has_key(att):
                    self.value = float(all_nodes[att].get_content())
                else:
                    self.value = float(att)
            except ValueError:
                raise SpecificationError, "<operator> '%s': invalid 'value' attribute '%s' (needs to be a number)" \
                      % (self.name, att)

        # "lower" gives the upper boundary for the lower X% of the values (default); while "upper" gives
        # the lower boundary fo the upper X% of the values.
        self.variant = get_attribute(elmnt_tree, "<operator> '%s'" % self.name, 'variant', 'lower',
                                     ("lower", "upper"))
        self.cmp_fcn = cmp
        if self.variant == 'upper':
            self.cmp_fcn = self._reverse_cmp

        self._build_result_info()
        self._setup_target_table(db)

        if self.value is None:
            raise SpecificationError, "<operator> '%s': 'quantile' needs a 'value' attribute" % self.name

        # see above
        # XXX does this apply here? Inactivated the check with "False and"
        if False and (len(self.input_names) == 1 and isinstance(self.sources[self.input_names[0]], operator)):
            self.param_infos = []

        return

    def _reverse_cmp(self, x, y):
        return -cmp(x,y)

    def _get_result_name(self, result_infos):
        if self.op_type != "quantile":
            new_name = self.op_type + "("
        else:
            percents = str(self.value).rstrip('0')
            if percents[-1:] == ".":
                percents += "0"
            new_name = percents + '-' + self.op_type + "("

        for ri in result_infos:
            new_name += ri[1] + ","
        return new_name[:-1] + ')'

    def _reduce_vector(self, db, table_name = None):
        """Reduce a single result value (the vector) into a scalar value."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name
        op = self.op_type

        # for now, used by quantile operator
        for r_i in self.result_infos:
            if self.scope == "run":
                # We need to get all available 'run order index' value; a separate reduction will
                # be performed for each run.
                sqlexe(crs, "SELECT DISTINCT %s FROM %s" % (pb_runorder_colname, op_tbl))
                order_idx = get_crs_column(crs, 0)               
            else:
                order_idx = [-1]

            for run_idx in order_idx:
                if run_idx < 0:
                    # For each result value requested, we have to aggregate separately
                    sqlexe(crs, "SELECT %s FROM %s" % (r_i[0], op_tbl),
                           "#* DEBUG: globally reducing data vector with %s operator:" % op)
                else:
                    # For each result value requested, we have to aggregate separately
                    sqlexe(crs, "SELECT %s FROM %s WHERE %s=%s" % (r_i[0], op_tbl, pb_runorder_colname, run_idx),
                           "#* DEBUG: reducing run-local data vector with %s operator:" % op)

                # Create a single sequence of all returned values, which then is sorted
                # to calculate the quantile. 
                db_rows = crs.fetchall()
                all_vals = []
                for row in db_rows:
                    all_vals.append(row[0])
                all_vals.sort(self.cmp_fcn)

                # We use the empirical distribution function. Others might be implemeted and
                # accessed via an attribute (not yet defined).
                # CHECK: the combination of ceil() and "-1" looks redundant!
                q_idx = min(int(ceil(len(all_vals)*self.value/100.0)) - 1, len(all_vals)-1)
                sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, r_i[0], all_vals[q_idx]),
                       "#* DEBUG: updating data vector with:")
        db.commit()
        return

    def _aggregate_dataset(self, results):
        "Will be called for quantile operator"
        results.sort(self.cmp_fcn)
        q_idx = min(int(ceil(len(results)*self.value/100.0))-1, len(results)-1)
        val = results[q_idx]
        return str(val)


class distrib_operator(operator):
    """Used for distrib, which accumulates the values of a data vector into bins
    to visualize the distribution of samples.
    A bin is a constant interval; the size of this interval is either specified
    by the user, or determined automatically. For an input vector of data, this
    operator returns an output vector which contains the number of elements in
    each bin."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1          # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!
        self.n_bins = 100          # number of auto-bins is set to 100 - what is reasonable?
        
        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)
        
        self.is_sql_op = False
        self.exact_aggregate = False
        self.can_reduce = True
        self.count_samples = False
        # Actually, it is not really a reduction, but a vector-to-vector transformation.
        # But we need to consider this as a reduction to have the related be called.        

        # Get the width of each bin. If not specified, it will be chosen automatically
        # based on the min and max values.
        att = mk_label(elmnt_tree.get('value'), all_nodes)
        if att != None:
            try:
                if all_nodes.has_key(att):
                    self.value = float(all_nodes[att].get_content())
                else:
                    self.value = float(att)
            except ValueError:
                raise SpecificationError, "<operator> '%s': invalid 'value' attribute '%s' (needs to be a number)" \
                      % (self.name, att)

        # supported variants are "cumulative", "normalized" and "absolute" (default)
        self.variant = get_attribute(elmnt_tree, "<operator> '%s'" % self.name, 'variant', 'absolute',
                                     ("cumulative", "normalized", "absolute", "nonzero"))
        self.option = get_attribute(elmnt_tree, "<operator> '%s'" % self.name, 'option', 'none',
                                    ('samples'))
            
        self._build_result_info()
        self._setup_target_table(db)

        return

    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""

        # Only a single result info is supported - check for this!?
        if len(self.src_result_infos) != 1:
            raise DataError, "'distrib' operator can only be applied on a single result value!"
            
        ri = self.src_result_infos[0]
        lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
        if  lbl_type == "auto":
            new_name = "samples(" + ri[0] + ")"
        elif lbl_type == "empty":
            new_name = ""
        elif lbl_type == "ignore":
            new_name = ri[1]
        elif lbl_type == "parameter":
            new_name = ""                     
        elif lbl_type == "explicit":                
            new_name = self.inp_label_text[self.input_names[0]]
        else:
            if be_verbose():
                print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
            new_name = "???"

        # Special case for "distrib" operator: the operator reports 'sample numbers' (integers)
        # no matter what the type of source result values is!
        new_labels = ri[6]
        if self.option == "samples":
            # CHECK: the if above did also check for 'and ri[6] is not None and len(ri[6]) > 0:' - why?
            if len(new_labels) > 0:
                new_labels += pb_label_sep
            new_labels += "N_samples = " + pb_filter_str
            self.count_samples = True
        if self.variant == "absolute" or self.variant == "nonzero":
            ri_bincount = ('bin_'+ri[0], new_name, 'integer(4)','integer', '',
                           "sample value count", new_labels)
        elif self.variant == "normalized":
            ri_bincount = ('bin_'+ri[0], new_name, 'float(4)','float', '',
                           "probability [%]", new_labels)
        elif self.variant == "cumulative":
            ri_bincount = ('bin_'+ri[0], new_name, 'float(4)','float', '',
                           "cumulative probability [%]", new_labels)
        self.value_src_map[mk_info_key(ri_bincount)] = self.value_src_map[mk_info_key(ri)]
        self.result_infos = []
        self.result_infos.append(ri_bincount)

        # Strip of any additional parameter vectors as they do not make any sense after we
        # tranformed the result vector into a distribution.
        self.param_infos = []

        # We need to add another param_info here, which are the bin limits. Adding a new param_info
        # is not really supported, but with some special attention in _create_bin_vector, we can make
        # it work reliably.
        self.new_p_info = [ri[0], 'bin(%s)'%ri[0], ri[2], ri[3], ri[4],
                           "sample value distribution", ri[6]]
        self.param_infos.append(self.new_p_info)
            
        return

    def _create_bins(self, min_val, bin_width, samples):
        """Return a vector of bins, which means that each entry in the vector represents
        the number of samples that fit into this bin. The bins are determined by the min_val
        and the bin_width, and the number of samples, and the chosen variant"""
        bin_limit = min_val + bin_width
        add_bins = 0
        bin_idx = 0

        bins = []
        if self.variant == "absolute":
            bins.append(0)
        else:
            bins.append(float(0))
        for s in samples:
            if s > bin_limit:
                add_bins = int(1 + floor((s - bin_limit)/bin_width))
                bin_limit += bin_width*add_bins

            if add_bins > 0:
                current_val = bins[bin_idx]
                bin_idx += add_bins
                while add_bins > 0:
                    if self.variant == "cumulative":
                        bins.append(current_val)
                    else:
                        if self.variant == "absolute":
                            bins.append(0)
                        else:
                            bins.append(float(0))
                    add_bins -= 1

            if self.variant == "absolute":
                bins[bin_idx] += 1
            else:
                bins[bin_idx] += 100/float(len(samples))

        # add a closing bin with count zero to support plotting
        #bins.append(0)
        return bins

    def _create_bin_vector(self, db, table_name = None):
        """Convert the samples from one or more runs into one distribution vector."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        # Hack: temporarily remove the additional parameter from the list as it must not be
        # considered in the next operations.
        self.param_infos.remove(self.new_p_info)
        
        param_sets = self._build_param_sets(db, op_tbl)

        if len(param_sets) != 1:
            # We may only have a single parameter set here, for which a (large) number of
            # samples is provided. From these samples, we create the distribution.
            raise DataError, "'bin' operator can only work for s single set of parameter value contents!"
        p_set_idx = 0

        # For the distribution, we have to create *two* new rows in the output table for this
        # parameter set: the first (parameter) column are bin limits, which are derived from
        # the range of the sample values or specified by the user. The second (result) column
        # are the number of elements in each bin.
        col_str = pb_origin_colname + ","
        val_str = "'" + self.name + "',"
        for p_idx in range(len(self.param_infos)): 
            col_str += self.param_infos[p_idx][0] + ","
            val_str += get_sql_contents(self.param_infos[p_idx],
                                        param_sets[p_set_idx][p_idx]) + ","
        for r_idx in range(len(self.result_infos)):
            col_str += self.result_infos[r_idx][0] + ","
        # col_str and val_str will be extended further down!

        # Only a single result info is used.
        r_i = self.src_result_infos[0]

        # Now, retrieve all data sets for the parameter set in use, derive the distribution
        # from it, and store the resulting vectors in the output table.
        p_condition = ""
        for p_idx in range(len(self.param_infos)):
            p_condition += " %s = %s AND" % (self.param_infos[p_idx][0],
                                             get_sql_contents(self.param_infos[p_idx],
                                                              param_sets[p_set_idx][p_idx]))                    
        p_condition = p_condition[:-len("AND")]
        if len(p_condition) > 0:
            p_condition = "WHERE %s" % p_condition

        sqlexe(crs, "SELECT %s FROM %s %s" % (r_i[0], op_tbl, p_condition),
               "#* DEBUG: bin-operator is getting all samples")
        db_rows = crs.fetchall()

        # hack again: re-insert "our" parameter
        self.param_infos.append(self.new_p_info)
        col_str += self.param_infos[len(self.param_infos)-1][0] + ","
        col_str = col_str[:-1]

        # Create a single vector for the samples that will be processed.
        samples = []
        for row in db_rows:
            samples.append(row[0])
        samples.sort()

        if len(samples) > 0:
            min_val = samples[0]
            max_val = samples[len(samples)-1]
            if self.value is None:
                # determine bin width automatically
                bin_width = (max_val - min_val)/self.n_bins
            else:
                bin_width = self.value
                # Adjust the min_val to the specified bin_width.
                min_val = floor(min_val/bin_width)*bin_width

            bins = self._create_bins(min_val, bin_width, samples)

            if do_debug():
                print "#* DEBUG: creating new data sets for distribution:" 
            bin_limit = min_val
            for b in bins:
                if self.variant == "absolute":
                    next_val_str = "%s%d,%e" % (val_str, b, bin_limit)
                else:
                    next_val_str = "%s%e,%e" % (val_str, b, bin_limit)
                sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, next_val_str))

                bin_limit += bin_width

        # set value of N_samples
        if self.count_samples:
            self.updated_filters.append(("N_samples", "%d" % len(samples)))

        crs.close()
        return

    def _create_count_vector(self, db, table_name = None):
        """Convert the samples from one or more runs into one vector with a count element for each distinct value."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        # Hack: temporarily remove the additional parameter from the list as it must not be
        # considered in the next operations.
        self.param_infos.remove(self.new_p_info)
        
        param_sets = self._build_param_sets(db, op_tbl)

        if len(param_sets) != 1:
            # We may only have a single parameter set here, for which a (large) number of
            # samples is provided. From these samples, we create the distribution.
            raise DataError, "'bin' operator can only work for s single set of parameter value contents!"
        p_set_idx = 0

        # For the distribution, we have to create *two* new rows in the output table for this
        # parameter set: the first (parameter) column are the values found in the input vector
        # The second (result) column is the count of each value.
        col_str = pb_origin_colname + ","
        val_str = "'" + self.name + "',"
        for p_idx in range(len(self.param_infos)): 
            col_str += self.param_infos[p_idx][0] + ","
            val_str += get_sql_contents(self.param_infos[p_idx],
                                        param_sets[p_set_idx][p_idx]) + ","
        for r_idx in range(len(self.result_infos)):
            col_str += self.result_infos[r_idx][0] + ","
        # col_str and val_str will be extended further down!

        # Only a single result info is used.
        r_i = self.src_result_infos[0]

        # Now, retrieve all data sets for the parameter set in use, count the values,
        # and store the resulting vectors in the output table.
        p_condition = ""
        for p_idx in range(len(self.param_infos)):
            p_condition += " %s = %s AND" % (self.param_infos[p_idx][0],
                                             get_sql_contents(self.param_infos[p_idx],
                                                              param_sets[p_set_idx][p_idx]))                    
        p_condition = p_condition[:-len("AND")]
        if len(p_condition) > 0:
            p_condition = "WHERE %s" % p_condition

        sqlexe(crs, "SELECT %s,count(%s) FROM %s %s GROUP BY %s" % (r_i[0], r_i[0], op_tbl, p_condition, r_i[0]),
               "#* DEBUG: bin-operator is counting all samples")
        db_rows = crs.fetchall()

        # hack again: re-insert "our" parameter
        self.param_infos.append(self.new_p_info)
        col_str += self.param_infos[len(self.param_infos)-1][0] + ","
        col_str = col_str[:-1]

        for row in db_rows:
            next_val_str = "%s%d,%e" % (val_str, row[1], row[0])
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, next_val_str))

        # set value of N_samples
        if self.count_samples:
            self.updated_filters.append(("N_samples", "%d" % len(db_rows)))

        crs.close()
        return

    def _aggregate_runs(self, db, table_name = None):
        """Transform (not reduce) data from a single source into a distribution vector."""
        if self.variant != "nonzero":
            return self._create_bin_vector(db, table_name)
        else:
            return self._create_count_vector(db, table_name)

    def _reduce_vector(self, db, table_name = None):
        """Transform (not reduce) a single result vector into a distribution vector."""
        if self.variant != "nonzero":
            return self._create_bin_vector(db, table_name)
        else:
            return self._create_count_vector(db, table_name)


class slice_operator(operator):
    """Used for slice, which cuts arbitrary contiguous pieces out of an input vector. This
    means that the result is again a vector of same or shorter length, often even a scalar."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 0          # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!
        
        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)
        
        self.is_sql_op = False
        # Actually, it is not really a reduction, but a vector-to-vector transformation.
        # But we need to consider this as a reduction to have the related function be called.        

        # Hmm, the result *might* be a single-element vector, which would actually
        # be a reduction, but it can also be a multi-element vector Problem? I don't
        # think so because the reduction-characteristics do not rely on the size of the
        # result, but on the type of operation that is performed.
        self.can_reduce = True

        # Get the slice definition, which actually is given in Python array-slice syntax.
        # By default, we use the full vector (null operator)
        if self.op_type == "latest":
            self.slice = "[-1:]"
        elif self.op_type == "oldest":
            self.slice = "[:1]"
        else:
            # custom slice - by default, deliver the complete vector
            self.slice = "[:]"
            att = mk_label(elmnt_tree.get('value'), all_nodes)
            if att != None:
                if re.compile("^\[((-[0-9]+)|[0-9]*):((-[0-9]+)|[0-9]*)\]$").search(att) is None:
                    raise SpecificationError, "<slice> operator '%s': invalid syntax in slice definiton '%s'" % (self.name, att)
                self.slice = att                
        # no supported variants or options
            
        self._build_result_info()
        self._setup_target_table(db)

        return

    def _aggregate_runs(self, db, table_name = None):
        """In this case, aggreation and reduction are the same thing."""
        return self._reduce_vector(db, table_name)        

    def _reduce_vector(self, db, table_name = None):
        """Get a single value from the data table . Here, we might also produce vectors with more than
        one value."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        # First, get all available 'run order index' value. The slice will operate on this index.
        sqlexe(crs, "SELECT DISTINCT %s FROM %s" % (pb_runorder_colname, op_tbl))
        order_idx = get_crs_column(crs, 0)
        qry_idx = eval("order_idx" + self.slice)
        qry_idx.sort()

        # The query operates on all parameters and info values available.
        val_list = "%s,%s," % (pb_runidx_colname, pb_runorder_colname)
        for r_i in self.result_infos:
            val_list += r_i[0] + ","
        for p_i in self.param_infos:
            val_list += p_i[0] + ","

        try:
            sqlexe(crs, "SELECT %s FROM %s WHERE %s >= %d AND %s <= %d" % (val_list[:-1], op_tbl,
                                                                           pb_runorder_colname, qry_idx[0],
                                                                           pb_runorder_colname, qry_idx[len(qry_idx)-1]),
                   "#* DEBUG: slicing data vector with slice %s" % self.slice) 
        except IndexError:
            raise SpecificationError, "<slice> operator '%s': invalid range in slice definiton '%s'" \
                  % (self.name, self.slice)
        nim = build_name_idx_map(crs)

        for row in crs.fetchall():
            values = "%d,%d," % (row[0], row[1])
            for r_i in self.result_infos:
                values += get_sql_contents(r_i, row[nim[r_i[0].lower()]]) + ","
            for p_i in self.param_infos:
                values += get_sql_contents(p_i, row[nim[p_i[0].lower()]]) + ","
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, val_list[:-1], values[:-1]),
                   "#* DEBUG: inserting slice row")
        
        return


class runindex_operator(operator):
    """Map a result value to the related run"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self._build_result_info()
        self._setup_target_table(db)

        self.is_sql_op = False

        return
        
    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this
        operator within the result_info structure to be created.
        Here, we create an integer vector as result for all kind of
        input data.
        """
        
        self.result_infos = []

        if len(self.src_result_infos) != 1:
            raise SpecificationError, "<operator> %s: runindex operator requires exactly 1 result value." % self.name
        
        for ri in self.src_result_infos:
            lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
            if  lbl_type == "auto":
                new_name = self._get_result_name([ri])
            elif lbl_type == "empty":
                new_name = ""
            elif lbl_type == "ignore":
                new_name = ri[1]
            elif lbl_type == "parameter":
                new_name = ""                     
            elif lbl_type == "explicit":                
                new_name = self.inp_label_text[self.input_names[0]]
            else:
                if be_verbose():
                    print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                new_name = "???"

            ri_new = [ri[0], new_name, 'integer', 'integer', "",
                      "run index for content of %s" % ri[1], ri[6]]
            self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
            self.result_infos.append(ri_new)
        
        return

    def _aggregate_runs(self, db, table_name = None):
        """In this case, aggreation and reduction are the same thing."""
        return self._reduce_vector(db, table_name)        

    def _reduce_vector(self, db, table_name = None):
        """Not a reduction, but a tranformation."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        # The query operates on all parameters and info values available.
        val_list = "%s,%s," % (pb_runidx_colname, pb_runorder_colname)
        for r_i in self.result_infos:
            val_list += r_i[0] + ","
        for p_i in self.param_infos:
            val_list += p_i[0] + ","

        sqlexe(crs, "SELECT %s FROM %s" % (val_list[:-1], op_tbl),
               "#* DEBUG: getting runindex for result")
        nim = build_name_idx_map(crs)

        for row in crs.fetchall():
            values = "%d,%d," % (row[0], row[1])
            # Now, simply do not store the content of the result value, but its runindex!
            # We ensure that we only  have a single result value!
            values += "%d," % row[0]
            for p_i in self.param_infos:
                values += get_sql_contents(p_i, row[nim[p_i[0].lower()]]) + ","
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, val_list[:-1], values[:-1]),
                   "#* DEBUG: inserting runindex row")
        
        return

class param_info:
    def __init__(self, name, sql_type, pb_type, unit, syno):
        self.name = name
        self.sql_type = sql_type
        self.pb_type = pb_type
        self.unit = unit
        self.syno = syno
        return

class param_operator(operator):
    """The param operator maps a run index to the content of a parameter value in this run."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        att = mk_label(elmnt_tree.get('value'), all_nodes)
        if att is None:
            raise SpecificationError, "<operator> %s: 'value' attribute has to specify a parameter name." % self.name
            
        # get required information on this parameter
        crs = db.cursor()
        sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (att, ))
        if crs.rowcount != 1:
            raise SpecificationError, "<operator> %s: '%s' is not a parameter name." % (self.name, att)
        nim = build_name_idx_map(crs)
        row = crs.fetchone()
        if row[nim['is_result']]:
            raise SpecificationError, "<operator> %s: '%s' is a result, not a parameter." % (self.name, att)
        if not row[nim['only_once']]:
            raise SpecificationError, "<operator> %s: '%s' has to be a only-once parameter." % (self.name, att)

        self.param = param_info(att, row[nim['sql_type']], row[nim['data_type']],
                                row[nim['data_unit']], row[nim['synopsis']])

        self._build_result_info()
        self._setup_target_table(db)

        self.quote= ""
        if pb_sql_string_types.has_key(self.param.pb_type):
            self.quote = "'"
        self.is_sql_op = False

        return
        
    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this
        operator within the result_info structure to be created.
        The problem here is that we need to determine the type of the
        output data (the parameter) which is not a parameter neither a
        result value that is passed up. We determined this within
        __init__."""
        
        self.result_infos = []

        if len(self.src_result_infos) != 1:
            # Can only operate on the one, single vector of run indexes, which is the
            # result vector in this case.
            raise SpecificationError, "<operator> %s: param operator requires exactly 1 result value." % self.name
        
        for ri in self.src_result_infos:
            lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
            if lbl_type == "auto":
                new_name = self.param.name
            elif lbl_type == "empty":
                new_name = ""
            elif lbl_type == "ignore":
                new_name = ri[1]
            elif lbl_type == "parameter":
                new_name = ""                     
            elif lbl_type == "explicit":                
                new_name = self.inp_label_text[self.input_names[0]]
            else:
                if be_verbose():
                    print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                new_name = "???"

            ri_new = [ri[0], new_name, self.param.pb_type, self.param.sql_type, self.param.unit,
                      self.param.name + " for "+ ri[1], ri[6]]
            self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
            self.result_infos.append(ri_new)
        
        return

    def _aggregate_runs(self, db, table_name = None):
        """In this case, aggreation and reduction are the same thing."""
        return self._reduce_vector(db, table_name)        

    def _reduce_vector(self, db, table_name = None):
        """Not a reduction, but a tranformation."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        cache = {}

        # The query operates on all parameters and info values available.
        val_list = "%s,%s," % (pb_runidx_colname, pb_runorder_colname)
        for r_i in self.result_infos:
            val_list += r_i[0] + ","
        for p_i in self.param_infos:
            val_list += p_i[0] + ","

        sqlexe(crs, "SELECT %s FROM %s" % (val_list[:-1], op_tbl), "#* DEBUG: getting runindex for result")
        nim = build_name_idx_map(crs)

        db_rows = crs.fetchall()
        for row in db_rows:
            r_idx = row[0]
            if r_idx < 0:
                raise DataError, "<operator> %s: found invalid run index (-1)." % self.name
            
            values = "%d,%d," % (r_idx, row[1])
            # Now, simply do not store the runindex, but the content of the chosen parameter
            # has in this run.
            try:
                param_val = cache[r_idx]
            except:
                sqlexe(crs, "SELECT %s FROM rundata_once WHERE run_index = %d" % (self.param.name, r_idx))
                if crs.rowcount == 0:
                    raise DataError, "<operator> %s: no parameter content for run index %d." % (self.name. r_idx)                
                param_val = crs.fetchone()[0]
                cache[r_idx] = param_val
            
            values += "%s%s%s," % (self.quote, param_val, self.quote)
            for p_i in self.param_infos:
                values += get_sql_contents(p_i, row[nim[p_i[0].lower()]]) + ","
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, val_list[:-1], values[:-1]),
                    "#* DEBUG: inserting runindex row")
        
        return


class resolve_operator(operator):
    """The resolve operator checks all open filter and replaces the place holder with a value
    if (and only if) the run_index of N% (default N=100) data rows is identical. This is a simple
    optimization technique. Additionally, two attributes can be specified to speficy which
    deviations from the 100% rule should be tolerated, and how to calculate such deviations."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1        # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self.is_sql_op == False

        # get all open filters, and extract the parameter names from them
        self.open_params = []
        ri_idx = 0
        for ri in self.src_result_infos:
            if ri[6].find(pb_filter_str) > 0:
                filters = ri[6].replace(pb_label_sep, ' ').split(' ')
                while True:
                    try:
                        idx = filters.index(pb_filter_str)
                    except ValueError:
                        break
                    self.open_params.append((filters[idx-2], ri_idx))
                    filters.remove(pb_filter_str)
                    ri_idx += 1

        # determine all *real* parameter names (current might be an alias)
        # XXX not yet implemented - how?
        
        # check the parameters
        crs = db.cursor()
        for op in self.open_params:
            sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (op[0], ))
            if crs.rowcount != 1:
                raise SpecificationError, "<operator> %s: '%s' is not a parameter name, or an alias (not supported)." \
                      % (self.name, op[0])
            nim = build_name_idx_map(crs)
            row = crs.fetchone()
            if row[nim['is_result']]:
                raise SpecificationError, "<operator> %s: '%s' is a result, not a parameter." % (self.name, op[0])
            if not row[nim['only_once']]:
                raise SpecificationError, "<operator> %s: '%s' has to be a only-once parameter." % (self.name, op[0])

        # attribute "variant": how is the allowed discrepancy of "all parameter value contents are identical"
        # calculated?
        # "fraction": a fraction of N% of the contents may be different to still consider 
        #             all contents identical.
        # "stddev": the standard deviation must not be bigger than N to consider all contents
        #           identical.
        self.variant = get_attribute(elmnt_tree, "<operator> %s" % self.name, "variant",
                                     'fraction', ['fraction', 'stddev'])
        # attribute "value": provide the value N for the variant above.
        self.value = float(mk_label(get_attribute(elmnt_tree, "<operator> %s" % self.name, "value", '0', None),
                                    all_nodes))
        
        self._build_result_info()
        self._setup_target_table(db)

        return
        
    def _get_result_name(self, result_infos):
        """This operator doesn't change the data, thus keep the old name."""
        new_name = ""
        for ri in result_infos:
            new_name += ri[1] + ","
        return new_name[:-1]

    def _aggregate_runs(self, db, table_name = None):
        """In this case, aggreation and reduction are the same thing."""
        return self._reduce_vector(db, table_name)        

    def _reduce_vector(self, db, table_name = None):
        """Not a reduction, but a tranformation."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        # First, we need to pass through the data!
        sqlexe(crs, "SELECT * FROM %s" % op_tbl)
        nim = build_name_idx_map(crs)
        
        val_list = "%s,%s,%s," % (pb_origin_colname,pb_runidx_colname, pb_runorder_colname)
        for r_i in self.result_infos:
            val_list += r_i[0] + ","
        for p_i in self.param_infos:
            val_list += p_i[0] + ","
        for row in crs.fetchall():
            values = "'%s',%s,%s," % (self.name, row[nim[pb_runidx_colname]], row[nim[pb_runorder_colname]])
            for r_i in self.result_infos:
                values += get_sql_contents(r_i, row[nim[r_i[0].lower()]]) + ","
            for p_i in self.param_infos:
                values += get_sql_contents(p_i, row[nim[p_i[0].lower()]]) + ","
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (self.tgt_table, val_list[:-1], values[:-1]))

        if len(self.open_params) == 0:
            # we're done
            return
        
        # We first check the run-ids of all results on identity etc. Only if the run_ids
        # are *not* identical, we need to check the actual content of the parameter value
        # for the listed run-ids.
        sqlexe(crs, "SELECT DISTINCT %s FROM %s" % (pb_runidx_colname, op_tbl))
        all_runids = zip(*crs.fetchall())[0]
        if len(all_runids) == 1:
            # the simple case!
            for op in self.open_params:
                sqlexe(crs, "SELECT %s FROM rundata_once WHERE run_index=%d" % (op[0], all_runids[0]))
                ri = self.src_result_infos[op[1]]
                new_ri = (ri[0], ri[1], ri[2], ri[3], ri[4], ri[5],
                          ri[6].replace(pb_filter_str, str(crs.fetchone()[0])))
        elif len(all_runids) > 1:
            # Need to dig deeper. First, check if even for different run_ids, the value content
            # actually differs!            
            for op in self.open_params:
                p_val = None
                for r in all_runids:
                    sqlexe(crs, "SELECT %s FROM rundata_once WHERE run_index=%d" % (op[0], r))
                    v = crs.fetchone()[0]
                    if p_val is not None and v != p_val:
                        # Difference!
                        p_val = None
                        break
                    p_val = v
                if p_val == None and self.value > 0:
                    # Dig even depper!
                    print "NOT IMPLEMENTED."
                else:
                    ri = self.src_result_infos[op[1]]
                    new_ri = (ri[0], ri[1], ri[2], ri[3], ri[4], ri[5],
                              ri[6].replace(pb_filter_str, str(p_val)))

        print "ALLRUNS", all_runids, self.open_params
        print "NEW_RI", new_ri[6]
        return


class minmax_operator(operator):
    """Used for min and max"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 0  # number of inputs required (0 means unlimited)
        self.need_params = False   # This operator may operate on results-only vectors

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self.scope = get_attribute(elmnt_tree, "<operator> %s" % self.name, "scope",
                                   'global', ['run', 'global'])

        self._build_result_info()
        self._setup_target_table(db)

        self.is_sql_op = True

        return
        
    def _reduce_vector(self, db, table_name = None):
        """Reduce a single result value (the vector) into a scalar value."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name
        op = self.op_type

        lookup_val = None
        lookup_name = None
        for r_i in self.result_infos:
            if self.scope == "run":
                # We need to get all available 'run order index' value; a separate reduction will
                # be performed for each run.
                sqlexe(crs, "SELECT DISTINCT %s FROM %s" % (pb_runorder_colname, op_tbl))
                order_idx = get_crs_column(crs, 0)               
            else:
                order_idx = [-1]

            for run_idx in order_idx:
                if run_idx < 0:
                    sqlexe(crs, "SELECT %s(%s) FROM %s" % (op, r_i[0], op_tbl),
                           "#* DEBUG: globally reducing data vector with %s operator:" % op)
                else:
                    sqlexe(crs, "SELECT %s(%s) FROM %s WHERE %s=%s" % (op, r_i[0], op_tbl, pb_runorder_colname, run_idx),
                           "#* DEBUG: reducing run-local data vector with %s operator:" % op)

                # Store the result value set in the output table together with the
                # matching parameter set. This is only possible if there is only
                # one result value.
                row = crs.fetchone()
                new_val = row[0]
                if new_val is None:
                    # It is possible that there is no data at all!
                    continue

                if len(self.result_infos) == 1:
                    val_list = "%s,%s," % (pb_runidx_colname, pb_runorder_colname)
                    for p_i in self.param_infos:
                        val_list += p_i[0] + ','
                    sqlexe(crs, "SELECT %s FROM %s WHERE %s=%s" % (val_list[:-1], op_tbl, r_i[0], str(new_val)))

                    val_list += r_i[0]
                    db_row = crs.fetchone()
                    values = "%d,%d," % (db_row[0], db_row[1])
                    for i in range(len(self.param_infos)):
                        values += get_sql_contents(self.param_infos[i], db_row[2+i])+","
                    values += str(new_val)
                    sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (self.tgt_table, val_list, values))
                else:
                    # Only the scalar value. No run-index or order is stored, neither. Could be fixed!?
                    if not lookup_val:
                        sql_cmd = "INSERT INTO %s (%s,%s,%s) VALUES (%s,%d,%d)" % (output_table, r_i[0],
                                                                                   pb_runidx_colname, pb_runorder_colname,
                                                                                   str(new_val), -1, -1)
                        lookup_val = new_val
                        lookup_name = r_i[0]
                    else:
                        sql_cmd = "UPDATE %s SET %s=%s,%s=%s,%s=%s WHERE %s = %s" % (output_table, r_i[0], str(new_val),
                                                                                     pb_runidx_colname, -1,
                                                                                     pb_runorder_colname, -1,
                                                                                     lookup_name, str(lookup_val))
                    sqlexe(crs, sql_cmd)
        
        db.commit()
        return            

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        sql_cmd = "SELECT "

        for n in self.input_names:
            ri = (self.sources[n].get_result_info())[result_idx]            
            sql_cmd += self.src_tables[n] + '.' + pb_runidx_colname + ',' + \
                       self.src_tables[n] + '.' + pb_runorder_colname + ',' + \
                       self.src_tables[n] + '.' + ri[0] + ','
        # adding the FROM clause even if all tables are already specified became
        # necessary with PostgreSQL 8.x
        sql_cmd = sql_cmd[:-1] + " FROM "
        for t in self.src_tables.itervalues():
            sql_cmd += t + ","

        try:
            sqlexe(crs, sql_cmd[:-1] + row_filter, "#* DEBUG: minmax._calculate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)
        db_rows = crs.fetchall()

        # Some operators require more calculations. We could do them within
        # the SQL query, but for now, we chose to do it in Python.
        op_rows = []
        for row in db_rows:
            # We need to build a data-only vector to operate on, then recover
            # the run-order and -index from the original vector.
            data_row = []
            for i in range(len(row)/3):
                # data is only stored in every 3rd entry, starting with index 2
                data_row.append(row[i*3+2])
            val = eval(self.op_type)(data_row)
            idx = data_row.index(val)            
            op_rows.append(row[3*idx:3*idx+4])

        return op_rows


class rel_operator(operator):
    """Used for percentof, above, below"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 2  # number of inputs required (0 means unlimited)
        self.need_params = False   # This operator does not need parameter data vectors

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self._build_result_info()
        self._setup_target_table(db)

        self.can_reduce = False   
        self.exact_aggregate = False
        
        return
        
    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""
        
        op_sign = { "percentof":" % of ", "above":" % more than ", "below":" % less then "}
        op_synopsis = { "percentof":"", "above":"relative increase", "below":"relative decrease"}

        self.result_infos = []
        for r in range(len(self.sources[self.input_names[0]].get_result_info())):
            lbl_type = self.inp_label_type[self.input_names[0]]
            ri = (self.sources[self.input_names[0]].get_result_info())[r]
            
            if  lbl_type == "auto":
                new_name = "["
                ri_prev = None
                # We need to go backwards to create a valid statement.
                for n_idx in range(len(self.input_names)-1, -1, -1):
                    # Need to check if the result values are of the same type.
                    # XXX Ideally, we would also check the unit and (if necessary)
                    # create the new unit for the result. To be done!
                    ri = (self.sources[self.input_names[n_idx]].get_result_info())[r]
                    if ri_prev and ri[2] != ri_prev[2]:
                        raise SpecificationError, "<operator> '%s': non-matching result values" % self.name
                    new_name += ri[1] + op_sign[self.op_type]
                    ri_prev = ri
                new_name = new_name[:-len(op_sign[self.op_type])] + "]"
            elif lbl_type == "empty":
                new_name = ""
            elif lbl_type == "ignore":
                new_name = ri[1]
            elif lbl_type == "parameter":
                new_name = ""                     
            elif lbl_type == "explicit":                
                new_name = self.inp_label_text[self.input_names[0]]
            else:
                if be_verbose():
                    print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                new_name = "???"

            # ratios always need to be float values
            ri_new = [ri[0], new_name, 'float(4)', 'float', '%', op_synopsis[self.op_type],
                      self._match_filters(r)]
            self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
            self.result_infos.append(ri_new)

        return

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        op_mapping = {'percentof':'/', 'above':'/', 'below':'/'}
        sql_cmd = "SELECT (100*"
        p = ")"

        for n in self.input_names:
            ri = (self.sources[n].get_result_info())[result_idx]
            sql_cmd += self.src_tables[n] + '.' + ri[0] + p + op_mapping[self.op_type]
            p = ""
        sql_cmd = sql_cmd[:-len(op_mapping[self.op_type])] + " FROM "

        # adding the FROM clause even all tables are already specified became
        # necessary with PostgreSQL 8.x
        for t in self.src_tables.itervalues():
            sql_cmd += t + ","

        sql_cmd = sql_cmd[:-1] + row_filter
        if self.op_type == "percentof" :
            if row_filter[-5:] != "WHERE":
                sql_cmd += " AND"
            sql_cmd += " " + self.src_tables[n] + '.' + ri[0] + " != 0"
             
        try:
            sqlexe(crs, sql_cmd, "#* DEBUG: rel._calculate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)
        db_rows = crs.fetchall()

        # In this operator, the run_order and run_idx entries aren't useful: the
        # operation does always relate two values from two different runs - which run
        # information should be used? It might make sense to use the information of the run
        # which is *not* the reference, but for now, we just mark the corresponding value
        # with invalid content.

        # Some operators require more calculations. We could do them within
        # the SQL query, but for now, we chose to do it in Python.
        op_rows = []
        for row in db_rows:
            if row[0] is None:
                # This has been observed - why?
                continue

            if self.op_type == "percentof":
                op_rows.append([-1, -1, row[0]])
            elif self.op_type == "above":
                op_rows.append([-1, -1, row[0] - 100])
            elif self.op_type == "below":
                op_rows.append([-1, -1, 100 - row[0]])

        return op_rows


class transform_operator(operator):
    """Used for scale, offset and normalize"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        global pb_valid_scales
        
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        # Can not reduce multiple values, but only modify each single value
        self.can_reduce = False  

        valid_units = ["auto"]
        for u in pb_valid_baseunits.iterkeys():
            valid_units.append(u)
        # TODO: check attribute against 'valid_units' - but this does not include scaling.
        self.fixed_unit = get_attribute(elmnt_tree, "<operator> %s" % self.name, "unit",
                                   "auto")
        self.dtype = get_attribute(elmnt_tree, "<operator> %s" % self.name, "option",
                                   "auto", ['float', 'integer', 'auto'])
        
        # 'scale' and 'offset' operators need a value attribtue
        att = mk_label(elmnt_tree.get('value'), all_nodes)
        if all_nodes.has_key(att):
            scale_str = all_nodes[att].get_content()
        else:
            scale_str = att

        if self.op_type == "normalize":
            self.variant = get_attribute(elmnt_tree, "<operator> %s" % self.name, "variant",
                                         "offset", ['offset', 'scale'])
            self.unit_scale = None

            if att == None:
                self.value = 1.0
                if self.variant == "offset":
                    self.value = 0.0
            # Need to get first element from this vector as scaling is relative to it.
        else:
            self.variant = self.op_type

            if att == None:
                raise SpecificationError, "<operator> '%s': 'scale' or 'offset' need a 'value' attribute" % self.name
            try:
                self.inverse_scale = False
                if scale_str[:2] == "1/":
                    scale_str = scale_str[2:]
                    self.inverse_scale = True

                if pb_valid_scales.has_key(scale_str):
                    self.unit_scale = pb_valid_scales[scale_str]
                    self.value = float(pb_scale_values[self.unit_scale])
                else:
                    self.value = float(scale_str)
                    self.unit_scale = None

                if self.inverse_scale:
                    self.value = 1/self.value
            except ValueError:
                raise SpecificationError, "<operator> '%s': invalid 'value' attribute '%s' (needs to be a number, a '1/x expression, or a 10-/2-base scale symbol)" \
                          % (self.name, scale_str)

        self._build_result_info()
        self._setup_target_table(db)

        return

    def _get_result_name(self, result_infos):
        rval = result_infos[0][1]
        if self.op_type == "normalize":
            op_text = { "scale":" normalized to ", "offset":" shifted to " }
            return rval + op_text[self.variant] + str(self.value)
        else:
            op_sign = { "scale":"*", "offset":"+" }
            return rval + op_sign[self.op_type] + str(self.value)

    def _scale_unit(self, unit_str):
        """Replace the existing scaling by an adjusted (reverse) scaling if necessary."""

        # Determine the current scale prefix.
        scale_prefix = None
        scale_val = 1
        # Need to sort it to avoid that only "K" matches "Ki" (and not "Ki")
        scale_letters = []
        for s in pb_scale_values.iterkeys():
            scale_letters.append(s)
        scale_letters.sort()
        for s in scale_letters:
            if len(unit_str) >= len(s) and unit_str[:len(s)] == s:
                scale_prefix = s
        if scale_prefix:
            scale_val = pb_scale_values[scale_prefix]
        
        if not self.inverse_scale:
            rvs_scale = 1/pb_scale_values[self.unit_scale]
        else:
            rvs_scale = pb_scale_values[self.unit_scale]
        new_scale_val = scale_val*rvs_scale
        
        if not pb_scale_values_reverse.has_key(new_scale_val):
            print "#* WARNING: <operator> %s: can not scale unit when scaling by '%s'" \
                  % (self.name, self.unit_scale)
            new_unit_str = unit_str
        else:
            rvs_scale_str = pb_scale_values_reverse[new_scale_val]
            if len(unit_str) == 0:
                new_unit_str = rvs_scale_str
            elif pb_valid_baseunits.has_key(unit_str):
                new_unit_str = rvs_scale_str + unit_str
            elif pb_scale_values.has_key(unit_str[0]):
                new_unit_str = rvs_scale_str + unit_str[len(scale_prefix):]
            else:
                raise SpecificationError, "Invalid scaling operation!"
        return new_unit_str

    def _build_result_info(self):
        self.result_infos = []

        if len(self.input_names) == 1:
            for ri in self.src_result_infos:
                lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
                if  lbl_type == "auto":
                    new_name = self._get_result_name([ri])
                elif lbl_type == "empty":
                    new_name = ""
                elif lbl_type == "ignore":
                    new_name = ri[1]
                elif lbl_type == "parameter":
                    new_name = ""                     
                elif lbl_type == "explicit":                
                    new_name = self.inp_label_text[self.input_names[0]]
                else:
                    if be_verbose():
                        print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                    new_name = "???"

                unit = ri[4]
                if self.unit_scale:
                    unit = self._scale_unit(unit)
                if self.fixed_unit != "auto":
                    unit = self.fixed_unit

                new_sqltype = ri[2]
                new_dtype = ri[3]
                if self.dtype != "auto":
                    new_sqltype = '%s(8)' % self.dtype
                    new_dtype = self.dtype
                ri_new = [ri[0], new_name, new_sqltype, new_dtype, unit, ri[5], ri[6]]
                self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
                self.result_infos.append(ri_new)
        else:
            for r in range(len(self.sources[self.input_names[0]].get_result_info())):
                lbl_type = self.inp_label_type[self.input_names[0]]
                if  lbl_type == "auto":
                    r_infos = []
                    ri_prev = None
                    for sn in self.input_names:
                        # Need to check if the result values are of the same type.
                        # Ideally, we would also check the unit. To be done!
                        ri = (self.sources[sn].get_result_info())[r]
                        r_infos.append(ri)
                        if ri_prev and ri[2][:4] != ri_prev[2][:4]:
                            raise SpecificationError, "<operator> '%s': non-matching result values" % self.name
                        ri_prev = ri
                    new_name = self._get_result_name(r_infos)
                elif lbl_type == "empty":
                    new_name = ""
                elif lbl_type == "ignore":
                    ri = (self.sources[self.input_names[0]].get_result_info())[r]
                    new_name = ri[1]
                elif lbl_type == "parameter":
                    new_name = ""                     
                elif lbl_type == "explicit":                
                    new_name = self.inp_label_text[self.input_names[0]]
                else:
                    if be_verbose():
                        print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                    new_name = "???"

                unit = ri[4]
                if self.unit_scale:
                    unit = self._scale_unit(unit)
                if self.fixed_unit != "auto":
                    unit = self.fixed_unit

                new_sqltype = ri[2]
                new_dtype = ri[3]
                if self.dtype != "auto":
                    new_sqltype = '%s(8)' % self.dtype
                    new_dtype = self.dtype
                ri_new = [ri[0], new_name, new_sqltype, new_dtype, unit, ri[5], ri[6]]
                self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
                self.result_infos.append(ri_new)

        return

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        op_mapping = {'scale':'*', 'offset':'+'}
        ri = self.src_result_infos[result_idx] 

        sql_cmd = "SELECT %s,%s," % (pb_runidx_colname, pb_runorder_colname)
        # If the datatype stays the same, we can embed the transformation into
        # the SQL query. Otherwise, we need to get the raw data and transform
        # it on the client side (below). Same for normalization.
        if self.dtype == "auto" and self.op_type != "normalize":
            sql_cmd += ri[0] + op_mapping[self.op_type] + str(self.value) + ' FROM ' + \
                       self.src_tables[self.input_names[0]]
        else:
            sql_cmd += ri[0] + ' FROM ' + self.src_tables[self.input_names[0]]
        try:
            sqlexe(crs, sql_cmd, "#* DEBUG: transform._calculate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)

        if self.dtype == "auto" and self.op_type != "normalize":
            return crs.fetchall()
        
        tf_data = []
        if self.op_type == "normalize":
            # Get the first element to cllculate the scaling factor. 
            row = crs.fetchone()
            tf_data.append((row[0], row[1], self.value))
            if self.variant == "scale":
                self.value = self.value/float(row[2])
            else:
                self.value = -float(row[2])

        for row in crs.fetchall():
            if self.variant == "scale":
                val = row[2] * self.value
            else:
                val = row[2] + self.value
            tf_data.append((row[0], row[1], val))
        return tf_data


class filter_operator(operator):
    """Used for limit and other operators which do not modify data, but filter it
    according to some criteria."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # No parameter data vectors required!

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        # Can not really reduce multiple values, but datasets will be removed from the
        # vector which is the same in this context
        self.can_reduce = True  
        self.cond_map = { 'less':'<', 'lessequal':'<=', 'equal':'=', 'notequal':'!=',
                          'greaterequal':'>=', 'greater':'>', 'null':'',
                          'false': 'NOT', 'true' : '' }
        
        # The 'limit' filter supports some attributes:
        if self.op_type in ( 'limit', 'abslimit' ):
            self.use_abs = False
            if self.op_type == 'abslimit':
                self.use_abs = True
                
            self.variant = get_attribute(elmnt_tree, "<operator> %s" % self.name, "variant",
                                         "null", ['less', 'lessequal', 'equal', 'notequal',
                                                  'greater', 'greaterequal', 'null', 'false', 'true'])

            self.value = mk_label(get_attribute(elmnt_tree, "<operator> %s" % self.name, "value"),
                                  all_nodes)
            if self.variant not in ( "null", "false", "true"):
                if self.value is None:
                    raise SpecificationError, "<operator> '%s': missing 'value' attribute" % (self.name)
                try:
                    self.limit = float(self.value)
                except ValueError:
                    raise SpecificationError, "<operator> '%s': invalid content '%s' for attribute 'value' (must be number)" \
                          % (self.name, self.value)

            # The name of the value to be filtered can be specified here. By default, it's the
            # (first) result value.
            self.filter_val = get_attribute(elmnt_tree, "<operator> %s" % self.name, "option")

            if self.filter_val is None:
                self.filter_val = self.src_result_infos[0][0]
            else:
                # check that the filter value does exist.
                crs = db.cursor()
                sqlexe(crs, "SELECT * FROM exp_values WHERE name = '%s'" % self.filter_val)
                if crs.rowcount == 0:
                    raise SpecificationError, "<operator> '%s': invalid content '%s' for attribute 'option' (not a value)" \
                          % (self.name, self.filter_val)                    

        self._build_result_info()
        self._setup_target_table(db)

        return

    def _get_result_name(self, result_infos):
        """This operator doesn't change the data, only filters data."""
        new_name = ""
        for ri in result_infos:
            if self.use_abs:
                new_name += "abs(" + ri[1] + ")"
            else:
                new_name += ri[1]
        if self.variant != "null":
            new_name += ",%s%s%s " % (self.filter_val, self.cond_map[self.variant], self.value)
        return new_name

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        ri = self.src_result_infos[result_idx] 

        sql_cmd = "SELECT %s,%s," % (pb_runidx_colname, pb_runorder_colname)
        if self.variant in ('false', 'true'):
            sql_cmd += "%s FROM %s WHERE %s%s" % (ri[0], self.src_tables[self.input_names[0]],
                                                    self.cond_map[self.variant], self.filter_val)
        else:
            sql_cmd += "%s FROM %s WHERE %s%s%s" % (ri[0], self.src_tables[self.input_names[0]],
                                                    self.filter_val, self.cond_map[self.variant],
                                                    self.limit)
        try:
            sqlexe(crs, sql_cmd, "#* DEBUG: filter._calculate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)

        return crs.fetchall()

    def _aggregate_runs(self, db, table_name = None):
        """In this case, aggreation and reduction are the same thing."""
        return self._reduce_vector(db, table_name)        

    def _reduce_vector(self, db, table_name = None):
        """Get a single value from the data table . Here, we might also produce vectors with more than
        one value."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        sql_cmd = "SELECT %s,%s," % (pb_runidx_colname, pb_runorder_colname)
        # The query operates on all parameters and info values available.
        val_list = "%s,%s," % (pb_runidx_colname, pb_runorder_colname)
        for r_i in self.result_infos:
            val_list += r_i[0] + ","
        for p_i in self.param_infos:
            val_list += p_i[0] + ","
        val = self.filter_val
        if self.use_abs:
            val = "abs(%s)" % self.filter_val
            
        if self.variant in ('false', 'true'):            
            sql_cond = " FROM %s WHERE %s %s" % (op_tbl, self.cond_map[self.variant], val)
        else:
            sql_cond = " FROM %s WHERE %s%s%s" % (op_tbl, val, self.cond_map[self.variant], self.limit)
        
        sql_cmd += val_list[:-1] + sql_cond
        sqlexe(crs, sql_cmd, "#* DEBUG: filter._reduce_vector(): SQL for result retrieval:")
        nim = build_name_idx_map(crs)

        for row in crs.fetchall():
            values = "%d,%d," % (row[0], row[1])
            for r_i in self.result_infos:
                values += get_sql_contents(r_i, row[nim[r_i[0].lower()]]) + ","
            for p_i in self.param_infos:
                values += get_sql_contents(p_i, row[nim[p_i[0].lower()]]) + ","
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, val_list[:-1], values[:-1]),
                   "#* DEBUG: inserting filter row")
        
        return


class pair_operator(operator):
    """Used for div and diff"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 2  # number of inputs required (0 means unlimited)
        self.need_params = True   # This operator needs parameter data vectors (for selection of parameter sets)

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self.is_sql_op = True
        self.can_reduce = False   
        self.exact_aggregate = False
        
        self._build_result_info()
        self._setup_target_table(db)

        return
        
    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""

        # Pairwise difference or division between data sources.
        op_sign = { "diff":"-", "div":"/" }
        ri = []
        self.result_infos = []
        for r in range(len(self.sources[self.input_names[0]].get_result_info())):
            ri.append((self.sources[self.input_names[0]].get_result_info())[r])
            ri.append((self.sources[self.input_names[1]].get_result_info())[r])

            # Need to check if the result values are of compatible type.
            # XXX Ideally, we would also check the unit and (if necessary)
            # create the new unit for the result. To be done!
            if ri[0][2] != ri[1][2]:
                if ri[0][2][:3] == 'int' and ri[1][2][:3] == 'int':
                    new_pb_type = "integer(8)"
                elif ri[0][2][:3] in ('int', 'flo') and ri[1][2][:3] in ('int', 'flo'):
                    new_pb_type = "float(8)"
                else:
                    # XXX Check for other valid operations, like int/duration...
                    raise SpecificationError, "<operator> '%s': unsupported operation '%s' on types '%s' and '%s' " \
                          % (self.name, self.op_type, ri[0][2], ri[1][2])
            else:
                if ri[0][2][:3] in ('tim', 'dat'):
                    if self.op_type == "div":
                        new_pb_type = "float(8)"
                    else:
                        new_pb_type = "duration"
                elif ri[0][2][:3] in ('int', 'flo'):
                    new_pb_type = ri[0][2]
                else:
                    raise SpecificationError, "<operator> '%s': invalid operation '%s' on types '%s' and '%s' " \
                          % (self.name, self.op_type, ri[0][2], ri[1][2])

            lbl_type = self.inp_label_type[self.input_names[0]]
            new_name = ""
            if  lbl_type == "auto":
                new_name += ri[0][1] + op_sign[self.op_type] + ri[1][1]
            elif lbl_type == "empty":
                pass
            elif lbl_type == "ignore":
                new_name = ri[0][1]
            elif lbl_type == "parameter":
                pass
            elif lbl_type == "explicit":                
                new_name = self.inp_label_text[self.input_names[0]]
            else:
                if be_verbose():
                    print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                new_name = "???"

            if self.op_type  == "diff":
                new_unit = ri[0][4]
            else:
                # XXX We could try to simplify the term, like "byte/us" -> "Mbyte/s"
                new_unit = ri[0][4] + '/' + ri[1][4]

            ri_new = [ri[0][0], new_name, new_pb_type, pb_valid_dtypes[new_pb_type],
                      new_unit, ri[0][5]+op_sign[self.op_type]+ri[1][5], self._match_filters(r)]
            self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri[0])]
            self.result_infos.append(ri_new)
        
        return

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        op_mapping = {'diff':'-', 'div':'/'}
        sql_cmd = "SELECT "
       
        for n in self.input_names:
            ri = (self.sources[n].get_result_info())[result_idx]
            sql_cmd += self.src_tables[n] + '.' + ri[0] + op_mapping[self.op_type]
        sql_cmd = sql_cmd[:-len(op_mapping[self.op_type])] + " FROM "
        # adding the FROM clause even all tables are already specified became
        # necessary with PostgreSQL 8.x
        for t in self.src_tables.itervalues():
            sql_cmd += t + ","
        sql_cmd = sql_cmd[:-1] + row_filter
        if self.op_type == "div":
            sql_cmd += " AND " + self.src_tables[n] + '.' + ri[0] + " != 0"

        try:
            sqlexe(crs, sql_cmd, "#* DEBUG: pair._calculate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)
        db_rows = crs.fetchall()

        # In this operator, the run_order and run_idx entries aren't useful: the
        # operation does always relate two values from two (different) runs - which run
        # information should be used? 
        op_rows = []
        for row in db_rows:
            op_rows.append([-1, -1, row[0]])
            
        return op_rows


class sum_operator(operator):
    """Used for sum"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 0  # number of inputs required (0 means unlimited)
        self.need_params = True   # This operator needs parameter data vectors (for selection of parameter sets)

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self._build_result_info()
        self._setup_target_table(db)

        self.is_sql_op = True
        self.exact_aggregate = False
        
        # see above
        if len(self.input_names) == 1 and isinstance(self.sources[self.input_names[0]], operator):
            self.param_infos = []
        
        return        

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        sql_cmd = "SELECT "
       
        for n in self.input_names:
            ri = (self.sources[n].get_result_info())[result_idx]
            sql_cmd += self.src_tables[n] + '.' + ri[0] + '+'
        # adding the FROM clause even all tables are already specified became
        # necessary with PostgreSQL 8.x
        sql_cmd = sql_cmd[:-1] + " FROM "
        for t in self.src_tables.itervalues():
            sql_cmd += t + ","
        try:
            sqlexe(crs, sql_cmd[:-1] + row_filter, "#* DEBUG: sum_calculate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)
        db_rows = crs.fetchall()

        # If we are here, we operate on more than one input vector, and keeping the
        # run index and order makes no sense. Set invalid values instead. For aingle-vector
        # summation, the run-information will be passed on correctly, though, as the
        # generic _reduce_vector() function is used.
        op_rows = []
        for row in db_rows:
            op_rows.append([-1, -1, row[0]])
            
        return op_rows


class sort_operator(operator):
    """Used for sort"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 0          # any number of inputs allowed
        self.need_params = False   # does not need parameter data vectors as it just sorts everything it gets

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self._build_result_info()
        self._setup_target_table(db)

        self.variant = get_attribute(elmnt_tree, "<operator> %s" % self.name, "variant",
                                     "ascending", ["none", "ascending", "descending"])
        variant_map = { "none":"", "ascending":"ASC", "descending":"DESC" }
        self.variant = variant_map[self.variant]

        self.sort_by = self.param_infos[0][0]
        att = mk_label(elmnt_tree.get('value'), all_nodes)
        if att != None:
            # find value(s) by which the sorting should be done
            good = []
            bad = []
            self.sort_by = None
            # treat comma like another white space separator so
            # that "foo,bar", "foo, bar" and "foo bar" are all
            # valid
            for atom in att.replace(',', ' ').split():
                for ri in self.result_infos + self.param_infos:
                    if ri[0] == atom:
                        good.append(atom)
                        break
                else:
                    bad.append(atom)
            if bad:
                raise SpecificationError, "<operator> '%s': 'value' attribute '%s' contains unknown value name(s) '%s'" \
                      % (self.name, att, " ".join(bad))
            else:
                # comma separated for SQL query
                self.sort_by = ",".join(good)

        self.is_sql_op = True
        self.can_reduce = False   
       
        return        

    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""       
        # We simply pass all data through, but avoid create duplicate columns in the
        # output table. Up to now, we just don't add a value which does already exist
        # which is a little bit simplistic. Instead, we should also check i.e. if we
        # should clear the filter string if it differs between the values etc. On the
        # other hand, the user should know what he is doing in this case...
        used_names = {}
        self.result_infos = []        
        for ri in self.src_result_infos:
            if not used_names.has_key(ri[0]):
                self.result_infos.append(ri)
                used_names[ri[0]] = True

        return

    def store_data(self, db, table_name = None):
        """Get data from the data sources, process it, and store it in the ouput table"""
        if do_profiling():
            t0 = time.clock()

        crs = db.cursor()

        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        if output_table in self.have_stored_data:
            if do_profiling():
                t0 = time.clock() - t0
                self.prof_data['store_data'].append(t0)
            return
        self.have_stored_data.append(output_table)

        if do_debug():
            print "#* DEBUG: store_data of <operator> %s" % self.name
            print self.tgt_table, self.src_tables

        #
        # Naive algorithm - does this work reliably? More efficient (in-place) sorting possible?
        #
        # First step: store all input data in a single query  table.
        for n in self.input_names:
            self.sources[n].store_data(db, output_table)

        col_str = "%s,%s," % (pb_runidx_colname, pb_runorder_colname)
        for pi in self.param_infos:
            col_str += pi[0] + ','
        for ri in self.result_infos:
            col_str += ri[0] + ','
        col_str = col_str[:-1]

        # Second step: read back data, sorted by SQL, and clear table
        sqlexe(crs, "SELECT %s FROM %s ORDER BY %s %s" % (col_str, output_table, self.sort_by, self.variant),
               "#* DEBUG: _operate(): SQL for sorted data retrieve:")
        db_rows = crs.fetchall()
        sqlexe(crs, "DELETE FROM %s" % output_table)

        # Final step: store data in output table.
        col_str = pb_origin_colname + ',' + col_str
        n_pi = len(self.param_infos)
        n_ri = len(self.result_infos)
        for row in db_rows:
            # Why can this be "None"?
            if row[0] is None:
                continue
            val_str = "'%s',%s,%s," % (self.name, row[0], row[1])
            for i in range(n_pi):
                val_str += get_sql_contents(self.param_infos[i], row[2 + i]) + ','
            for i in range(n_ri):
                val_str += get_sql_contents(self.result_infos[i], row[n_pi + 2 + i]) + ','
            val_str = val_str[:-1]
            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, val_str),
                   "#* DEBUG: _operate(): SQL for sorted data insert:")

        crs.close()
        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)

        return


class prod_operator(operator):
    """Used for prod"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 0  # number of inputs required (0 means unlimited)
        self.need_params = True   # This operator needs parameter data vectors (for selection of parameter sets)

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self._build_result_info()
        self._setup_target_table(db)

        self.exact_aggregate = False
        
        # see above
        if len(self.input_names) == 1 and isinstance(self.sources[self.input_names[0]], operator):
            self.param_infos = []
        
        return

    def _reduce_vector(self, db, table_name = None):
        """Reduce a single result value (the vector) into a scalar value."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name
        op = self.op_type

        for r_i in self.result_infos:
            # For each result value requested, we have to aggregate separately
            # No SQL function for product available
            sqlexe(crs, "SELECT %s,%s,%s FROM %s" % (pb_runidx_colname, pb_runorder_colname, r_i[0], op_tbl),
                   "#* DEBUG: reducing data vector with %s operator:" % op)

            # Store the parameter/result value set in the output table
            db_rows = crs.fetchall()
            new_val = 1
            for row in db_rows:
                new_val *= row[2]
            # Again, we can not be sure that the run information is actually meaningful: data 
            # from multiple runs might have been mixed up in the input object. However, we
            # optimistically store the according information from the last row.
            sqlexe(crs, "INSERT INTO %s (%s,%s,%s) VALUES (%d,%d,%s)" % (output_table, pb_runidx_colname,
                                                                         pb_runorder_colname, r_i[0],
                                                                         row[0], row[1], new_val),
                   "#* DEBUG: updating data vector with:")
                   
        db.commit()
        return            

    def _aggregate_dataset(self, results):
        "Will be called for prod operator"
        rval = 1.0
        for r in results:
            rval *= r
            
        return str(rval)

    def _calculate(self, crs, result_idx, row_filter):
        """Perform the calculations that are specific to the type of the operator."""
        sql_cmd = "SELECT "
       
        for n in self.input_names:
            ri = (self.sources[n].get_result_info())[result_idx]
            sql_cmd += self.src_tables[n] + '.' + ri[0] + '*'
        # adding the FROM clause even all tables are already specified became
        # necessary with PostgreSQL 8.x
        sql_cmd = sql_cmd[:-1] + " FROM "
        for t in self.src_tables.itervalues():
            sql_cmd += t + ","
        try:
            sqlexe(crs, sql_cmd[:-1] + row_filter, "#* DEBUG: prod_calculate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)

        # The data elements are from multiple runs; no sense in carrying run-related data along.
        # Store invalid values instead.
        op_rows = []
        for row in crs.fetchall():
            op_rows.append([-1, -1, row[0]])
            
        return op_rows


class count_operator(operator):
    """Used for count
       Operator 'count' counts values. 
       variant='total':    total count of values within a vector
       """
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1  # number of inputs required (0 means unlimited)
        self.need_params = False   # This operator does not need parameter data vectors

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)

        self.variant = get_attribute(elmnt_tree, "<operator> %s" % self.name, "variant",
                                     "total", ['total'])
        self.dtype = get_attribute(elmnt_tree, "<operator> %s" % self.name, "option",
                                   "integer", ['float','integer'])

        self._build_result_info()
        # This operator just count the number of rows in a table and reports this
        # number; it doesn't carry any parameters with it.

        if (len(self.input_names) == 1 and isinstance(self.sources[self.input_names[0]], operator)):
            self.param_infos = []

        self.exact_aggregate = False

        if self.variant == "total":
            self.can_reduce = True

        self._setup_target_table(db)
        return
        
    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""
        # Operator 'count' gives the number of runs that contribute to each data set.
        self.result_infos = []
        for ri in self.src_result_infos:
            lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
            if  lbl_type == "auto":
                new_name = self.op_type + "(" + ri[1] + ")"
            elif lbl_type == "empty":
                new_name = ""
            elif lbl_type == "ignore":
                new_name = ri[1]
            elif lbl_type == "parameter":
                new_name = ""                     
            elif lbl_type == "explicit":                
                new_name = self.inp_label_text[self.input_names[0]]
            else:
                if be_verbose():
                    print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                new_name = "???"

            # Special case for "count" operator: the operator reports 'counts' (integers)
            # no matter what the type of source result values is! We need a way to get float
            # values, which we have via the 'options' attribute.
            ri_new = [ri[0], new_name, '%s(4)' % self.dtype, self.dtype, '',
                      "number of runs containing matching data", ri[6]]
            self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
            self.result_infos.append(ri_new)
        
        return

    def _aggregate_dataset(self, results):
        "Only return the number of elements"
        if self.variant == "total":
            return str(len(results))


class eval_operator(operator):
    """Used for eval operators"""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 0  # number of inputs required (0 means unlimited)
        self.need_params = True   # This operator needs parameter data vectors (for selection of parameter sets)

        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)
        
        # Can not reduce multiple values, but only modify each single value
        self.can_reduce = False  
        self.exact_aggregate = False

        if self.op_type == "eval":
            self.eval_map = {}           
            term_nodes = elmnt_tree.findall('term')
            if len(term_nodes) != 1:
                raise SpecificationError, "<operator> '%s' of type 'eval' needs exactly one <term>" % (self.name)
            for t in term_nodes:
                self.eval_name = t.get('id')
                if not self.eval_name:
                    raise SpecificationError, "<operator> '%s': <term> needs an id attribute" % (self.name)
                self.eval_unit = t.get('unit')
                if not self.eval_unit:
                    self.eval_unit = ''

        # We need to create the related expressions.
        for t in term_nodes:
            self.eval_string = self._build_eval_string(t, sweep_alias)
            if do_debug():
                print "#* DEBUG: 'eval' operator"
                print "          ", self.eval_string

        self._build_result_info()
        self._setup_target_table(db)

        return
        
    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""
        
        self.result_infos = []
        # An 'eval' operator has only a single output value, no matter how many
        # inputs from how many sources it has.
        ri = self.src_result_infos[0]
        lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
        if  lbl_type == "auto":
            eval_args = ""
            for k in self.eval_map.iterkeys():
                eval_args += (k.split(pb_namesrc_sep))[0] + ','
            new_name = self.eval_name + '(' + eval_args[:-1] + ')'
        elif lbl_type == "empty":
            new_name = ""
        elif lbl_type == "ignore":
            new_name = ri[1]
        elif lbl_type == "parameter":
            new_name = ""
        elif lbl_type == "explicit":                
            new_name = self.inp_label_text[self.input_names[0]]
        else:
            if be_verbose():
                print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
            new_name = "???"
            
        # XXX We should try to construct a meaningful physical unit here (ri[4])!
        ri_new = [ri[0], new_name, 'float(8)', pb_valid_dtypes['float(8)'], self.eval_unit,\
                  self.eval_name, self._match_filters(0)]
        self.value_src_map[mk_info_key(ri_new)] = self.value_src_map[mk_info_key(ri)]
        self.result_infos.append(ri_new)

        return

    def _build_eval_string(self, term, sweep_alias):
        """Build a string that reflects the expression defined by the <term> description."""
        global pb_valid_funcs, pb_namesrc_sep
        constants = ('e', 'pi')
        
        t = term.find('fraction')
        if not t is None:
            divisor  = t.find('divisor')
            dividend = t.find('dividend')
            if dividend is None:
                raise SpecificationError, "no <dividend> in <fraction>"
            if divisor is None:
                raise SpecificationError, "no <divisor> in <fraction>"
            t_str = '('+self._build_eval_string(dividend, sweep_alias)+')/('+\
                    self._build_eval_string(divisor, sweep_alias)+')'
            return t_str
        t = term.find('difference')
        if not t is None:
            minuend = t.find('minuend')
            if minuend is None:
                raise SpecificationError, "no <minuend> in <difference>"
            subtrahend  = t.find('subtrahend')
            if subtrahend is None:
                raise SpecificationError, "no <subtrahend> in <difference>"
            t_str = '('+self._build_eval_string(minuend, sweep_alias)+')-('+\
                    self._build_eval_string(subtrahend, sweep_alias)+')'
            return t_str
        t = term.find('product')
        if not t is None:
            factors = t.findall('factor')
            if len(factors) == 0:
                raise SpecificationError, "no <factor> in <product>"
            t_str = '('
            for f in factors:
                t_str += self._build_eval_string(f, sweep_alias) + ')*('
            t_str = t_str[:-2]
            return t_str
        t = term.find('sum')
        if not t is None:
            summands = t.findall('summand')
            if len(summands) == 0:
                raise SpecificationError, "no <summand> in <sum>"
            t_str = '('
            for s in summands:
                t_str += self._build_eval_string(s, sweep_alias) + ')+('
            t_str = t_str[:-2]
            return t_str
        t = term.find('function')
        if not t is None:
            func = t.get('type')
            if not func:
                raise SpecificationError, "<function> requires attribute 'type'"
            if not pb_valid_funcs.has_key(func):
                raise SpecificationError, "Invalid <function> type '%s'" % func
            args = t.findall('argument')
            if len(args) != pb_valid_funcs[func]:
                raise SpecificationError, "<function> '%s' requires %d <arguments> (found %d)" \
                      % (func, pb_valid_funcs[func], len(args))
            t_str = func + '('
            for a in args:
                t_str += self._build_eval_string(a, sweep_alias) + ','
            t_str = t_str[:-1] + ')'
            return t_str
        t = term.find('variable')
        if not t is None:
            #  One of the input values, either referenced via an alias or its name.
            src = t.text
            if not src:
                raise SpecificationError, "<variable> requires the id of an <input>"
            if self.src_alias.has_key(src):
                src = self.src_alias[src]
            if sweep_alias is not None and sweep_alias.has_key(src):
                src = sweep_alias[src]
            if not self.sources.has_key(src):
                raise SpecificationError, "Unknown <input> id '%s' in <variable>" % src

            name = t.get('name')
            if not name:
                raise SpecificationError, "<variable> requires the attribute 'name'"
            # check if the name is valid.
            infos = []
            infos.append((self.sources[src].get_result_info(), 'result'))
            infos.append((self.sources[src].get_param_info(), 'param'))
            for i in infos:
                for r in range(len(i[0])):
                    if i[0][r][0] == name:
                        symkey = name + pb_namesrc_sep + src

                        dtype = t.get('type')
                        if dtype != None:
                            if dtype not in ("vector", "scalar"):
                                raise SpecificationError, "Invalid value '%s' for attribute 'type' of <variable>"
                            if dtype == "scalar":
                                # A scalar variable does only provide a single value, not a data vector!
                                self.scalar_var[src] = name
                                self.scalar_map[symkey] = src
                        if dtype is None or dtype == "vector":
                            self.eval_map[symkey] = (src, i[1], r)

                        return symkey
            raise SpecificationError, "'%s' in <variable> not found in <input> '%s' (use 'show=data' attribute!?)" \
                  % (name, src)
        
        # If we get here, we have a constant symbol. This can either be an internal constant (see
        # tuple 'constants', a 'fixed_value' (defined in the query) or a number
        t = term.find('constant')
        if not t is None:
            cnst = t.text
            if not cnst:
                raise SpecificationError, "empty <constant> in <term>"
            # Is it an internal constant?
            if cnst in constants:
                return cnst
            # Is it a valid number?
            try:
                f = float(cnst)
                return cnst  # it's a valid number
            except ValueError:
                pass
            # Is t a fixed value?
            if self.all_nodes.has_key(cnst) and isinstance(self.all_nodes[cnst], fixed):
                return self.all_nodes[cnst].get_content()
        # It's something invalid! We don't know what it is, though.
        raise SpecificationError, "Invalid content of <term>"
        return 
        
    def _calculate(self, crs, result_idx, row_filter):
        """Apply the user-specifed term to an arbitrary number of result values."""
        # The 'eval' operator can be applied to any number of inputs. But we don't
        # need to select rows if we have only one input source.
        if len(self.input_names) == 1:            
            row_filter = ""
            
        # In contrast to _operate which does the initial part of the calculation in SQL,
        # and only rest on a single result value in Python, we need to get all the
        # result values from the database to here, and do the complete calculation with
        # them here.
        srccol_map = {}
        # We get the run-information (index, order) from the first input object only. For
        # more input objects, this info doesn't make sense anyway if the runs are different.
        # If they were identical, we *could* use the information, but we currently do not
        # check for this.
        sql_cmd = "SELECT %s.%s,%s.%s," % (self.src_tables[self.input_names[0]], pb_runidx_colname,
                                           self.src_tables[self.input_names[0]], pb_runorder_colname)
        col = 2
        select_cnt = 0
        for n in self.input_names:
            if not self.scalar_var.has_key(n):
                select_cnt += 1
                infos = []
                infos.append((self.sources[n].get_result_info(), 'result'))
                infos.append((self.sources[n].get_param_info(), 'param'))
                for i in infos:
                    for r in range(len(i[0])):
                        sql_cmd += self.src_tables[n] + '.' + i[0][r][0] + ','
                        srccol_map[(n, i[1], r)] = col
                        col += 1
        # adding the FROM clause even all tables are already specified became
        # necessary with PostgreSQL 8.x
        sql_cmd = sql_cmd[:-1] + " FROM "
        for t in self.src_tables.itervalues():
            sql_cmd += t + ","
        sql_cmd = sql_cmd[:-1]
        if select_cnt > 1:
            sql_cmd += row_filter

        try:
            sqlexe(crs, sql_cmd, "#* DEBUG: eval_evaluate(): SQL for result retrieval:")
        except psycopg.ProgrammingError, error_msg:
            print "#* ERROR: Illegal SQL query:", error_msg
            exit(1)
        db_rows = crs.fetchall()
        
        results = []
        for row in db_rows:
            # Instead of messing around with this string, we should create an actual piece of code
            # which is a function representing the term and eval() it  - this should be faster?!
            estr = self.eval_string
            def tonumberstr(x):
                """take arbitray input (int, float, DateTimeDelta, string)
                and convert it to a string with a content that can be used in arithmetic operations
                (float)"""
                return "%.50e" % float(x)

            for k, v in self.eval_map.iteritems():
                estr = estr.replace(k, tonumberstr(row[srccol_map[v]]))
            for k, v in self.scalar_map.iteritems():
                estr = estr.replace(k, tonumberstr(self.scalar_var_content[v]))
            if do_debug():
                print "#* DEBUG: <operator> %s eval(): %s = %s" % (self.name, estr, str(eval(estr)))
            try:
                r = eval(estr)
            except ZeroDivisionError, error_msg:
                print "#* WARNING: division by zero in <operator> '%s' (term '%s')" % (self.name, estr)
                r = None

            if len(self.input_names) == 1:
                results.append([row[0], row[1], r])
            else:
                results.append([-1, -1, r])

        return results


class frequency_operator(operator):
    """Calculates the frequency of a data vector, which is the number of events
    (datapoints) per interval. Thus, it transform a 2D data-vector with parameter and result
    vector with into a data vector where the parameter vector has (p_last - p_first)/interval
    number of evenly distributed elements (the intervals), and the result vector has the same
    number of elements representing the number of data points that were found in this interval.
    ."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        self.n_inputs = 1          # number of inputs required (0 means unlimited)
        self.need_params = True   # No parameter data vectors required!
        
        operator.__init__(self, elmnt_tree, all_nodes, db, sweep_alias)
        
        self.exact_aggregate = False
        self.can_reduce = True
        # Actually, it is not really a reduction, but a vector-to-vector transformation.
        # But we need to consider this as a reduction to have the related function be called
        # by the operator class.

        # Get the interval width.
        # Default width of interval, which is 1 resulting in Hz for a second-timescale.
        self.intvl = 1.0 
        att = mk_label(elmnt_tree.get('value'), all_nodes)
        if att != None:
            try:
                if all_nodes.has_key(att):
                    self.intvl = float(all_nodes[att].get_content())
                else:
                    self.intvl = float(att)
            except ValueError:
                raise SpecificationError, "<operator> '%s': invalid 'value' attribute '%s' (needs to be a number)" \
                      % (self.name, att)

        # supported variants are "cumulative", "normalized" and "absolute" (default)
        self.variant = get_attribute(elmnt_tree, "<operator> '%s'" % self.name, 'variant', 'relative',
                                     ("relative", "absolute"))

        # Look at the phys. unit of the parameter - should be a time unit. Set the scaling of the frequency
        # accordingly, like 's' -> 'Hz', 'us' -> 'MHz'
        p_unit = self.param_infos[0][4]
        if p_unit[-1:] not in ('s', 'h', 'd', 'a'):
            print "#* WARNING: <operator> '%s' calculating frequency over a non-time based unit" % (self.name, )
            self.unit = ""
        else:
            scale_factor = 1
            self.unit = "Hz"
            for sv in pb_scale_values.iterkeys():
                if p_unit[0:len(sv)] == sv:
                    scale_factor = pb_scale_values[sv]
                    break
            self.unit = pb_scale_values_reverse[1/scale_factor] + 'Hz'
                            
        self._build_result_info()
        self._setup_target_table(db)
        return

    def _build_result_info(self):
        """Build a meaningful name for the result value(s) of this operator."""

        # Only a single result info is supported 
        if len(self.src_result_infos) > 1:
            raise DataError, "'frequency' operator can only be applied on a single result value!"

        if len(self.src_result_infos) > 0:
            ri = self.src_result_infos[0]
            lbl_type = self.inp_label_type[self.value_src_map[mk_info_key(ri)]]
            if  lbl_type == "auto":
                new_name = "freq(" + ri[0] + ")"
            elif lbl_type == "empty":
                new_name = ""
            elif lbl_type == "ignore":
                new_name = ri[1]
            elif lbl_type == "parameter":
                new_name = ""                     
            elif lbl_type == "explicit":                
                new_name = self.inp_label_text[self.input_names[0]]
            else:
                if be_verbose():
                    print "WARNING: unsupported content '%s' for attribute 'label' in %s" % (lbl_type, self.name)
                new_name = "???"
        else:
            new_name = 'freq()'
            ri = ('freq_unknown', new_name, 'float(4)','float', self.unit, "data frequency", '')

        # Special case for frequency operator: the operator reports a frequency (float)
        # no matter what the type of source result values is!
        ri_freqcount = ('freq_'+ri[0], new_name, 'float(4)','float', self.unit,
                        "data frequency", ri[6])
        if len(self.src_result_infos) > 0:
            self.value_src_map[mk_info_key(ri_freqcount)] = self.value_src_map[mk_info_key(ri)]

        self.result_infos = []
        self.result_infos.append(ri_freqcount)
            
        return

    def _aggregate_runs(self, db, table_name = None):
        """Not supported by this operator."""
        return self._reduce_vector(db, table_name)

    def _reduce_vector(self, db, table_name = None):
        """Transform (not reduce) a single result vector into a frequency vector."""
        crs = db.cursor()
        op_tbl = self.src_tables[self.input_names[0]]
        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name

        sqlexe(crs, "SELECT %s FROM %s" % (self.param_infos[0][0], op_tbl),
               "#* DEBUG: frequency-operator is getting all samples")
        db_rows = crs.fetchall()

        intvl_start = db_rows[0][0]
        intvl_end = intvl_start + self.intvl
        elmt_cnt = 0
        col_str = pb_origin_colname + "," + self.param_infos[0][0] + "," + self.result_infos[0][0]
        val_str = "'" + self.name + "',"

        # frequency starts with 0
        next_val_str = val_str + str(intvl_start) + ', 0'
        sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, next_val_str))

        for row in db_rows:
            # interval complete, store frequency and interval placement
            # also skip potential empty interval
            while row[0] >= intvl_end:
                next_val_str = val_str + str(intvl_start) + ',' + str(elmt_cnt/self.intvl)
                sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, next_val_str))

                elmt_cnt = 0
                intvl_start = intvl_end
                intvl_end = intvl_start + self.intvl
            # this is a non-emty interval - at least frequency 1
            elmt_cnt = elmt_cnt + 1

        # the final interval - frequency is 0 afterward (for step plotting)
        next_val_str = val_str + str(intvl_start) + ',' + str(elmt_cnt/self.intvl)
        sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, next_val_str))
        next_val_str = val_str + str(intvl_start+self.intvl) + ',' + str(elmt_cnt/self.intvl)
        sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, next_val_str))
        next_val_str = val_str + str(intvl_start+2*self.intvl) + ', 0'
        sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (output_table, col_str, next_val_str))
        
        crs.close()
        return
    
