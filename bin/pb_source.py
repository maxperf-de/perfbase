# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_source - Implementation of the source class used in queries.
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
from pb_query import *

import xml
import time
from sys import exit
from string import lower, strip, rstrip
from xml.etree import ElementTree

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg


class series:
    """This class provides an 'artifical' data vector, mainly used to index result vectors
    which have no parameter vector related."""
    def __init__(self, elmnt_tree):
        s = elmnt_tree

        self.type = "series"
        self.val_type = "number"
        self.idx_is_int = True

        self.name = s.get("id")
        if not self.name:
            raise SpecificationError, "each <series> needs an 'id' attribute"            

        self.s_name = s.findtext('name')
        if self.s_name is None or len(self.s_name) == 0:
            raise SpecificationError, "each <series> needs to have a 'name' element"

        if do_debug():
            print "#* DEBUG: initializing <series> '%s'" % self.s_name

        self.inc_op = '+'
        att = s.get('inc')
        if att:
            if not att in ('linear', 'exponential'):
                raise SpecificationError, "<series> '%s':  'inc' attribute has invalid content '%s'" \
                      % (self.name, att)
            if att == 'exponential':
                self.inc_op = '*'

        self.base = 1
        t = s.findtext('base')
        if not t is None:
            try:
                if t.isdigit():
                    self.base = int(t)
                else:
                    self.base = float(t)
                    self.idx_is_int = False
            except:
                raise SpecificationError, "<series> '%s':  'base' element has non-numerical content '%s'" \
                      % (self.name, t)

        self.increment = 1
        t = s.findtext('increment')
        if not t is None:
            try:
                if t.isdigit():
                    self.increment = int(t)
                else:
                    self.increment = float(t)
                    self.idx_is_int = False
            except:
                raise SpecificationError, "<series> '%s':  'base' element has non-numerical content '%s'" \
                      % (self.name, t)
                       
        self.synopsis = "numerical index"
        t = s.findtext('synopsis')
        if not t is None:
            self.synopsis = t
            
        # variable name (twice), pb and sql data unit, physical unit, synopsis and filter
        if self.idx_is_int:
            self.param_info = (self.s_name, self.s_name, 'integer', 'integer', 'none', self.synopsis, "")
        else:            
            self.param_info = (self.s_name, self.s_name, 'float', 'float', 'none', self.synopsis, "")
        self.result_infos = []

    def reset(self):
        self.next_val = self.base
        return

    def get_next_value(self):
        rval = self.next_val
        self.next_val = eval("rval" + self.inc_op + str(self.increment))
        return rval
        
    def get_param_info(self):
        return self.param_info

    def get_val_type(self):
        return self.val_type
        
    def get_name(self):
        return self.name
        
        
class source(data):
    """This class provides filtered data. Non-filtered data, taken directly from the database,
    is just a special case of this class when no filter is configured."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_alias = None):
        global pb_sweep_suffix, pb_label_sep

        data.__init__(self, elmnt_tree, all_nodes, db)

        et = elmnt_tree

        self.val_type = {}
        # The SQL SELECT ... WHERE expressions
        self.run_sql_filter = ""
        self.exp_sql_filter = ""
        # The internal (meta) data 
        self.param_infos = []
        self.result_infos = []
        self.result_values = {}
        self.constant_names = []
        self.tabular_names = []
        self.constant_rows = []
        self.series = []
        self.series_names = []
        self.showdata = {}
        self.have_performed_query = False
        self.have_stored_data = []
        self.table_rows = None
        self.type = "source"
        self.valid_input = []
        self.updated_filters = []
        self.order = "keep"
        self.sql_order = None
        self.chronology = None
        
        crs = db.cursor()

        self.name = et.get('id')
        if not self.name:
            raise SpecificationError, "each <source> needs a 'id' attribute"
        if sweep_alias != None:
            # Build a new name by appending the sweep suffixes of the underlying
            # parameters in an *ordered* manner. This means, the source with the
            # suffix '~2' uses the third (0.1,2) variation of the parameter. This
            # allows to group sources by their parameter variations just by grouping
            # sources with the same sweep index.
            # If multiple sweep parameters do exist, their suffixes are concanated by
            # dots ('.').
            self.name += pb_sweep_suffix
            for v in sweep_alias.itervalues():
                self.name += v + pb_sweep_suffix
            self.name = self.name[:-1]

        bool_expr = get_attribute(et, "<source> '%s'" % self.name, 'boolean', 'AND',
                                  ("AND", "OR", "NOT", "and", "or", "not")).upper()
        self.chronology = get_attribute(et, "<source> '%s'" % self.name, 'chronology',
                                        'created', ("created", "performed"))
            
        if do_debug():
            print "#* DEBUG: creating data source '%s'" % self.name

        p_nodes = et.findall('parameter')
        i_nodes = et.findall('input')
        for n in i_nodes:            
            if len(strip(n.text)) == 0:
                raise SpecificationError, "<source> '%s': <input> must not be empty" % self.name                

        # Collect embedded parameters, if any are provided. 
        self.params = []
        axis_label = {}
        for n in p_nodes:
            p = parameter(n, db, all_nodes)
            self.params.append(p)
            axis_label[p] = mk_label(n.get("axislabel"), all_nodes)
                
        # Get the parameters from the inputs
        for n in i_nodes:
            # 'external' parameter (might be a sweep parameter!)
            p_name = n.text
            if sweep_alias != None and sweep_alias.has_key(p_name):
                p_name = sweep_alias[p_name]
            if not all_nodes.has_key(p_name):
                raise SpecificationError, "<source> '%s': <input> %s is not defined" % (self.name, p_name)
            if isinstance(all_nodes[p_name], parameter):
                self.params.append(all_nodes[p_name])
                axis_label[all_nodes[p_name]] = mk_label(n.get("axislabel"), all_nodes)
            elif isinstance(all_nodes[p_name], series):
                self.series.append(all_nodes[p_name])
                
        for n in et.findall('series'):
            self.series.append(series(n))
        for s in self.series:
            p_info = s.get_param_info()
            self.param_infos.append(p_info)
            s_name = p_info[0]
            self.series_names.append(s_name)
            self.showdata[s_name] = True
            self.val_type[s_name] = s.get_val_type()
            
        filter_str = ""
        self.open_filters = []
        for p in self.params:
            p_info = p.get_param_info()
            if axis_label[p] is not None:
                p_info[4] = ""  
                p_info[5] = axis_label[p]
            p_name = p_info[0]
            self.param_infos.append(p_info)
            self.showdata[p_name] = p.showdata
            self.val_type[p_name] = p.get_val_type()
            if p.is_constant:
                self.constant_names.append(p_name)
            else:
                self.tabular_names.append(p_name)

            if p_info[6]:
                filter_str += p_info[6].strip()
                if p_info[6][-len(pb_filter_str):] == pb_filter_str or \
                       p_info[6][-4:] == "true" or p_info[6][-5:] == "false":
                    # array contains 'name', 'value to use', 'found value', 'valid_flag'
                    f = [p_name, None, None, False]
                    if p_info[6][-4:] == "true": 
                        f[1] = "true"
                    if p_info[6][-5:] == "false":
                        f[1] = "false"
                    self.open_filters.append(f)
                filter_str += pb_label_sep
                
            # build an SQL statement from the supplied filter specification
            sql_filter = p.get_sql_filter()
            if sql_filter:
                if p.is_constant:
                    self.exp_sql_filter += " (" + sql_filter + ") " + bool_expr
                else:
                    self.run_sql_filter += " (" + sql_filter + ") " + bool_expr
        filter_str = filter_str[:-len(pb_label_sep)]        

        # See which runs are to be considered at all! This can be provided via <run> tags
        # (either embedded or separately)
        self.valid_runs = None
        runs = []
        r_nodes = et.findall('run')
        for n in r_nodes:
            runs.append(run(n, db, all_nodes))
        for n in i_nodes:
            if sweep_alias != None and sweep_alias.has_key(n.text):
                # this is a sweep parameter, not a run
                continue
            if isinstance(all_nodes[n.text], run):
                runs.append(all_nodes[n.text])
        if len(runs) > 0:
            self.valid_runs = {}
            for r in runs:
                for idx in r.get_runs():
                    # Multiple <run>s are 'or' related
                    self.valid_runs[idx] = True
            # the runs specified in the query do not exist in the exeriment
            if len(self.valid_runs) == 0:
                raise SpecificationError, "none of the specified runs does exist in the experiment"

        # Collect & verify the result values. Acutally, it is also possible to
        # specify a parameter value here as a "result". This is useful to include
        # this data in to operator processing.
        r_nodes = et.findall('result')
        axis_label = {}
        if not r_nodes:
            raise SpecificationError, "<source> '%s': need at least one <result>" % self.name
        for r in r_nodes:            
            # Check if the result name is valid. Actually, is does not necessarily need to be a
            # result value - a parameter value can deliver the same data!
            r_name = r.text
            if all_nodes.has_key(r.text):
                r_name = all_nodes[r.text].get_content()
            r_alias = mk_label(get_attribute(r, r_name, 'alias', r_name, None), all_nodes)
            axis_label[r_name] = mk_label(r.get("axislabel"), all_nodes)
            
            sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (r_name, ))
            if crs.rowcount == 0:
                raise SpecificationError, "<source> '%s': <result> %s not found in experiment" % \
                      (self.name, r_name)
            if do_debug():
                print "#* DEBUG: adding result value '%s'" % r.text

            nim = build_name_idx_map(crs)
            self.showdata[r_name] = True
            
            db_row = crs.fetchone()
            # variable name (twice), pb and sql data unit, physical unit, synopsis and filter string
            ri = [r_name, r_alias, db_row[nim['data_type']], db_row[nim['sql_type']], 
                  db_row[nim['data_unit']], db_row[nim['synopsis']], filter_str]
            if axis_label[r_name] is not None:
                ri[4] = ""
                ri[5] = axis_label[r_name]
            self.result_values[r_name] = True
            self.result_infos.append(ri)
            self.val_type[r_name] = get_value_type(db_row, nim)
            if db_row[nim['only_once']]:
                self.constant_names.append(r_name)
            else:
                self.tabular_names.append(r_name)

        # User might want to sort the data at the source. For now, we sort according
        # to the first parameter value by default (if possible). If no parameter is present, 
        # use the first result value.
        order = get_attribute(et, self.name, 'order', 'ascending', ("keep", "ascending", "descending"))
        sort_key = get_attribute(et, self.name, 'key', None)
        if not sort_key:
            explicit_key = False
            if len(self.param_infos) > 0:
                sort_key = self.param_infos[0][0]
            else:
                sort_key = self.result_infos[0][0]
        else:
            found_key = False
            explicit_key = True
            for infos in (self.param_infos, self.result_infos):
                for p in infos:
                    if p[0] == sort_key:
                        found_key = True
                        break
            if not found_key:
                raise SpecificationError, "<source> '%s', attribute 'key=%s': %s not an active parameter." \
                      % (self.name, sort_key, sort_key)
        sqlexe(crs, "SELECT only_once FROM exp_values WHERE name='%s'" % (sort_key))
        if crs.rowcount == 0:
            if explicit_key:
                raise SpecificationError, "<source> '%s', attribute 'key=%s': invalid value name." \
                      % (self.name, sort_key)
            else:
                order = 'keep'
        else:
            if crs.fetchone()[0]:
                if explicit_key:
                    raise SpecificationError, "<source> '%s', attribute 'key=%s': value must have multiple occurence." \
                          % (self.name, sort_key)
                else:
                    order = 'keep'
                    
            if order == "ascending":
                self.sql_order = " ORDER BY %s ASC" % sort_key
            elif order == "descending":
                self.sql_order = " ORDER BY %s DESC" % sort_key
        
        if self.run_sql_filter:
            self.run_sql_filter = "AND (" + self.run_sql_filter[:rfind(self.run_sql_filter, " ")] + ")"
        else:
            self.run_sql_filter = None
        if self.exp_sql_filter:
            self.exp_sql_filter = "WHERE " + self.exp_sql_filter[:rfind(self.exp_sql_filter, " ")]
        else:
            self.exp_sql_filter = None
        if do_debug():
            print "#* DEBUG: source '%s' uses these SQL filters:" % self.name
            print "   per exp:", self.exp_sql_filter
            print "   per run:", self.run_sql_filter
            if self.valid_runs != None and len(self.valid_runs) > 0:
                print "#* DEBUG: source '%s' only queries these runs:" % self.name
                print "  ", self.valid_runs.keys()
        
        table_entries = []
        for j in (self.param_infos, self.result_infos):
            for i in j:
                if self.showdata[i[0]]:
                    table_entries.append((i[0], i[3]))
        try:
            self.tgt_table = create_query_table(db, table_entries)
        except SpecificationError, error_msg:
            print "#* ERROR: could not set up target table"
            print "  ", error_msg
            sys.exit(1)
                
        crs.close()
        return

    def _check_open_filters(self, crs, rows):
        """ Check for constant contents of filter-less parameters"""
        for f in self.open_filters:
            # find column index of this filter
            f_idx = -1
            for c_idx in range(len(crs.description)):
                if crs.description[c_idx][0] == f[0].lower():
                    f_idx = c_idx
                    break
            if f_idx >= 0:
                # Found it - now check if it is constant through all datasets
                for r in rows:
                    if f[2] == None:
                        if f[1] is None:
                            f[2] = r[c_idx]
                        else:
                            if r[c_idx] and f[1] == "true":
                                f[2] = f[0]
                            if not r[c_idx] and f[1] == "false":
                                f[2] = f[0]
                        f[3] = True
                        continue
                    elif f[3]:
                        if f[1] is None:
                            f[3] = (f[2] == r[c_idx])
                        else:
                            f[3] = ((f[1] == "true" and r[c_idx]) or (f[1] == "false" and not r[c_idx]))
                    else:
                        # Content is not constant, we can stop here.
                        break
        return
                        
    def perform_query(self, db):
        # Collect data for this source by iterating through all runtables of the experiment.
        # First, it is decided if the current runtable is used at
        # all by evaluating the static runtable-list (that the user
        # may have supplied), and check with the constants of each run by appyling
        # the per-experiment query. On the
        # remaining list of tables, the configured per-run query is 
        # performed, and the resulting data is copied into the
        # temporary query table. From there, the data to be written
        # to the output file is selected (and aggregated).
        if do_profiling():
            t0 = time.clock()

        if self.have_performed_query:
            if do_profiling():
                t0 = time.clock() - t0
                self.prof_data['perform_query'].append(t0)
            return
        self.have_performed_query = True
        
        crs = db.cursor()
        
        # Filter for active runs 
        # TODO: include user specified criterias here.
        active_runs = []
        sqlexe(crs, "SELECT index FROM run_metadata WHERE active ORDER BY %s ASC" % self.chronology,
               "#* DEBUG: source '%s' gathers all active runs:" % self.name)
        db_rows = crs.fetchall()
        if not db_rows:
            return        
        nim = build_name_idx_map(crs)
        for row in db_rows:
            if self.valid_runs is None or self.valid_runs.has_key(int(row[nim['index']])):
                active_runs.append(row[nim['index']])
        if do_debug():
            print "#* DEBUG: active runs:", active_runs

        # Either filter for constants in all runs (the filter can also be empty!), or select
        # the runs by the explicit selection via <run> elements.
        self.run_ids = []
        sql_cmd = "SELECT run_index"
        for n in self.constant_names:
            sql_cmd += "," + n
        if self.valid_runs is None:
            if self.exp_sql_filter == None:
                self.exp_sql_filter = ""

            sqlexe (crs, "%s FROM rundata_once %s" % (sql_cmd, self.exp_sql_filter),
                    "#* DEBUG: source '%s' performs experiment-global query on constants:" % self.name)
            nim = build_name_idx_map(crs)

            # If no rows are returned for a non-empty condtion, than there is not matching
            # data. In contrast, if no rows are returned for an empty condition, it means that
            # the table 'rundata_once' is just empty, meaning there is only tabular and no constant
            # data in this experiment.
            self.constant_rows = crs.fetchall()
            if not self.constant_rows:
                if len(self.exp_sql_filter) > 0:
                    # no matching runs
                    if do_profiling():
                        t0 = time.clock() - t0
                        self.prof_data['perform_query'].append(t0)
                    return
                else:
                    # all runs match if query was empty
                    self.run_ids.extend(active_runs)
            else:
                pop_idx = 0
                copy_rows = []
                copy_rows.extend(self.constant_rows)

                for row in copy_rows:
                    run_idx = row[nim['run_index']]
                    if run_idx in active_runs:
                        pop_idx += 1
                        self.run_ids.append(run_idx)
                    else:
                        # remove data from a run that is not to be considered
                        self.constant_rows.pop(pop_idx)
                
                self._check_open_filters(crs, self.constant_rows)
        elif len(self.constant_names) > 0 and len(self.valid_runs) > 0:
            # The user explicitely specified runs to be queried. But he may have specified filters
            # for only-once values as well! Both conditions get AND-related here.
            sql_cmd += " FROM rundata_once "
            if self.exp_sql_filter:
                sql_cmd += self.exp_sql_filter + " AND ("
            else:
                sql_cmd += "WHERE ("
            for r in self.valid_runs:
                sql_cmd += " run_index=%d OR" % r
            sqlexe(crs, sql_cmd[:-3] + ")",
                   "#* DEBUG: source '%s' performs experiment-global query on constants:" % self.name)
            self.constant_rows = crs.fetchall()
            if len(self.constant_rows) > 0:
                # need a list, not a tuple here
                self.run_ids = []
                self.run_ids.extend(zip(*self.constant_rows)[0])
            self._check_open_filters(crs, self.constant_rows)
        else:
            # No constant data to query or filter for, just add all id's for the tabular query.
            self.run_ids.extend(active_runs)

        if do_debug():
            print "#* DEBUG: Matching constant data:"
            for r in self.constant_rows:
                print "  ", r

        # Filter tabular data with the other parameters. The data of each table is then
        # stored in 'table_rows', in the same order as the constant data in 'constant_rows'
        self.table_rows = []
        if do_debug():            
            if len(self.tabular_names) > 0:                
                print "#* DEBUG: runs to be queried:", self.run_ids
            else:
                print "#* DEBUG: no tabular data is to be queried."
        if len(self.run_ids) == 0:
            # nothing to query here?
            if do_profiling():
                t0 = time.clock() - t0
                self.prof_data['perform_query'].append(t0)
            return
                
        if len(self.tabular_names) > 0:
            run_filter = "WHERE ("
            for i in self.run_ids:
                self.table_rows.append([])
                run_filter += "pb_run_index=%d OR " % i
            run_filter = run_filter[:-3] + ")"
            
            sql_cmd = "SELECT pb_run_index,"
            for n in self.tabular_names:
                sql_cmd += n + ","
            sql_cmd = rstrip(sql_cmd, ",")
            sql_cmd += " FROM rundata " + run_filter
            if self.run_sql_filter != None:
                sql_cmd += self.run_sql_filter
            if self.sql_order != None:
                sql_cmd += self.sql_order
            sqlexe(crs, sql_cmd,
                   "#* DEBUG: source '%s' performs run-related query:" % self.name)

            db_rows = crs.fetchall()
            nim = build_name_idx_map(crs)
            if not db_rows:
                if do_debug():
                    print"#* DEBUG: No matching tabular datasets found"

            self._check_open_filters(crs, db_rows)

            for r in db_rows:
                idx = r[nim['pb_run_index']]
                self.table_rows[self.run_ids.index(idx)].append(r)

            # We need an index which matches the non-empty datasets of tabular data
            # found below to the datasets of constant data gathered above. This is
            # not necessarily a one-on-one mapping as it may happen that a run has no
            # tabular data for a given set of constants! Such things can happen for
            # incomplete input files.
            self.tab_to_cnst_idx = []
            for t_idx in range(len(self.table_rows)):
                if len(self.table_rows[t_idx]) > 0:
                    self.tab_to_cnst_idx.append(t_idx)

            # drop all empty tables (means that no data was found in the corresponding run)
            try:
                while True:
                    self.table_rows.remove([])
            except ValueError:
                pass
                
            if len(self.table_rows) == 0:
                # No matching tabular data found, i.e. because run_ids was empty.
                # Thus, we also dump the constant data that may have been found.
                if do_debug():
                    print"#* DEBUG: No matching datasets found in this query"
                self.constant_rows = []

        # Replace open filter descriptions.
        f_value = None
        for ri in self.result_infos:
            if ri[6].count(pb_filter_str) > 0:
                for f in self.open_filters:
                    if f[3]:
                        f_value = "%s" % str(f[2])
                        ri[6] = ri[6].replace(pb_filter_str, f_value, 1)
                        self.updated_filters.append((f[0], f_value))
                break
            
        if do_debug():
            print "#* DEBUG: Matching tabular data:"
            print self.table_rows
        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['perform_query'].append(t0)
        return
    
    def get_param_info(self):
        """Provide a list of the parameter value names provided by this data source."""
        visible_params = []
        for p in self.param_infos:
            if self.showdata[p[0]]:
                visible_params.append(p)
        return visible_params

    def get_result_info(self):
        """Provide a list of the result value names provided by this data source."""
        return self.result_infos

    def update_filters(self):
        return self.updated_filters

    def get_next_paramset(self):
        return 

    def get_next_resultset(self):
        return

    def store_data(self, db, table_name = None):
        """Store the data of 'table_rows' and 'constant_rows' for processing (aggregation) by 
        an operator."""
        if do_profiling():
            t0 = time.clock()

        output_table = self.tgt_table
        if table_name is not None:
            output_table = table_name
            
        if output_table in self.have_stored_data:
            if do_debug():
                print "#* DEBUG: %s: data already stored to %s" % (self.name, output_table)
            if do_profiling():
                t0 = time.clock() - t0
                self.prof_data['store_data'].append(t0)
            return
        self.have_stored_data.append(output_table)
           
        crs = db.cursor()
        
        if do_debug():
            print "#* DEBUG: Inserting data of source '%s'into query table '%s':" % (self.name, output_table)
                        
        if not self.table_rows:
            # no tabular, only constant data
            for run_idx in range(len(self.constant_rows)):
                # list of tuples columns names and values which will be added
                insert_vals = []
                cmd_head = "INSERT INTO %s (%s,%s,%s," % (output_table, pb_origin_colname,
                                                          pb_runidx_colname, pb_runorder_colname)
                cmd_tail = ") VALUES ('%s',%d,%d," % (self.name, self.run_ids[run_idx], run_idx)

                sql_cmd = cmd_head
                for i in range(0, len(self.constant_names)):
                    if self.showdata[self.constant_names[i]]:
                        if self.constant_rows[run_idx][i+1] is None:
                            if be_verbose():
                                print "#* WARNING: NULL content for '%s'" % self.constant_names[i]
                            if self.constant_names[i] in self.result_values:
                                # Although undefined parameter values may make sense,
                                # we surely don't want a undefined result value!
                                insert_vals = []
                                break
                            # need to try next row
                            continue

                        vt = self.val_type[self.constant_names[i]]
                        cntnt = self.constant_rows[run_idx][i+1]
                        if vt == "number":
                            insert_vals.append((self.constant_names[i], cntnt))
                        elif vt == "boolean":
                            b = 'f'
                            if cntnt:
                                b = 't'
                            insert_vals.append((self.constant_names[i], b))
                        elif vt == "string":
                            insert_vals.append((self.constant_names[i], "'%s'" % clean_string(cntnt)))
                        elif vt == "date":
                            insert_vals.append((self.constant_names[i], "'%s'" % cntnt))

                if len(insert_vals) == 0:
                    continue
                
                for v in insert_vals:
                    cmd_head = cmd_head + v[0] + ','
                    cmd_tail = cmd_tail + str(v[1]) + ','               
                sqlexe(crs, cmd_head[:-1] + cmd_tail[:-1] + ')',)
        else:
            # tabular data (possibly combined with constant data)
            for run_idx in range(len(self.table_rows)):
                for s in self.series:
                    s.reset()
                for row_idx in range(len(self.table_rows[run_idx])):
                    # list of tuples columns names and values which will be added
                    insert_vals = []
                    cmd_head = "INSERT INTO %s (%s,%s,%s," % (output_table, pb_origin_colname, 
                                                              pb_runidx_colname, pb_runorder_colname)
                    cmd_tail = ") VALUES ('%s',%d,%d," % (self.name, self.run_ids[self.tab_to_cnst_idx[run_idx]],
                                                          run_idx)

                    for i in range(len(self.constant_names)):
                        if self.showdata[self.constant_names[i]]:
                            if self.constant_rows[run_idx][i+1] is None:
                                if be_verbose():
                                    print "#* WARNING: NULL content for '%s'" % self.constant_names[i]
                                if self.constant_names[i] in self.result_values:
                                    # Although undefined parameter values may make sense,
                                    # we surely don't want a undefined result value!
                                    insert_vals = []
                                    break
                                continue

                            vt = self.val_type[self.constant_names[i]]
                            cntnt = self.constant_rows[self.tab_to_cnst_idx[run_idx]][i+1]
                            if vt == "number":
                                insert_vals.append((self.constant_names[i], str(cntnt)))
                            elif vt == "boolean":
                                b = 'f'
                                if cntnt:
                                    b = 't'
                                    insert_vals.append((self.constant_names[i], b))
                            elif vt == "string":
                                insert_vals.append((self.constant_names[i], "'%s'" % clean_string(cntnt)))
                            elif vt == "date":
                                insert_vals.append((self.constant_names[i], "'%s'" % cntnt))

                    for i in range(len(self.tabular_names)):
                        if self.showdata[self.tabular_names[i]]:
                            # i + 1 to skip pb_run_index
                            if self.table_rows[run_idx][row_idx][i+1] is None:                                    
                                if be_verbose():
                                    print "#* WARNING: NULL content for '%s'" % self.tabular_names[i]
                                if self.tabular_names[i] in self.result_values:
                                    # Although undefined parameter values may make sense,
                                    # we surely don't want a undefined result value!
                                    insert_vals = []
                                    break
                                continue

                            vt = self.val_type[self.tabular_names[i]]
                            # i + 1 to skip pb_run_index
                            cntnt = self.table_rows[run_idx][row_idx][i+1]
                            if vt == "number":
                                insert_vals.append((self.tabular_names[i], str(cntnt)))
                            elif vt == "bool":
                                b = "'f'"
                                if cntnt:
                                    b = "'t'"
                                insert_vals.append((self.tabular_names[i], b))
                            elif vt == "string":
                                insert_vals.append((self.tabular_names[i], "'%s'" % clean_string(cntnt)))
                            elif vt == "date":
                                insert_vals.append((self.tabular_names[i], "'%s'" % cntnt))

                    if len(insert_vals) == 0:
                        # try next row from this run
                        continue;
                    for i in range(0, len(self.series_names)):
                        if self.showdata[self.series_names[i]]:
                            insert_vals.append((self.series_names[i], str(self.series[i].get_next_value())))

                    for v in insert_vals:
                        cmd_head = cmd_head + v[0] + ','
                        cmd_tail = cmd_tail + v[1] + ','
                    sqlexe(crs, cmd_head[:-1] + cmd_tail[:-1] + ')')
        db.commit()
        crs.close()
        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)
        return

    def remove_data(self, db):
        """Remove all data of this source from the given table."""
        crs = db.cursor()        
        sqlexe(crs, "DELETE FROM %s WHERE %s = '%s'" % (self.tgt_table, pb_origin_colname, self.name),
               "#* DEBUG: Removing data of source '%s'into query table '%s':" % (self.name, self.tgt_table))
        db.commit()
        
        return

