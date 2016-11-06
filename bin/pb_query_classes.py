# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_query_classes - All classees for pb_query.py which do not have their own module
#                    (to avoid circular imports)
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

from string import find, split, rfind, whitespace, lower, upper, strip, rstrip
from xml.etree import ElementTree
from sys import exit

import time
import re

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg


#
# classes
#
class combiner(data):
    """This class is able to merge the parameter and result vectors of two input objects
    into one output object. It allows to pass on only selected vectors.

    sweep_alias is a dictionary that maps the input names found to new input names
    created by a parameter sweep."""
    def __init__(self, elmnt_tree, all_nodes, db, sweep_regexp = None):
        global pb_all_ids, pb_sweep_suffix
        
        data.__init__(self, elmnt_tree, all_nodes, db)

        r = elmnt_tree

        self.updated_filters = []
        self.have_performed_query = False
        self.have_stored_data = []  # tables to which the data has been stored

        self.all_nodes = all_nodes
        self.type = "combiner"
        self.name = r.get('id')
        if not self.name:
            raise SpecificationError, "each <combiner> needs to have a 'id' attribute"

        if do_debug():
            print "#* DEBUG: initializing <combiner> %s" % self.name

        self.hide_double_params = True
        self.show_params = True
        att = get_attribute(r, "<combiner> %s" % self.name, "parameters", "unique", ["all", "none", "unique"])
        if att == "all":
            self.hide_double_params = False
        if att == "none":
            self.show_params = False

        # Convert the first result vector dimension into a parameter vector if necesary to
        # ensure there is a parameter vectore (required for output etc.).
        self.mkparam = False
        att = get_attribute(r, "<combiner> %s" % self.name, "mkparam", "no", ["yes", "no"])
        if att == "yes":
            self.mkparam = True

        self.sweep_group = r.get('sweep_group')

        self.datasets = get_attribute(r, "<combiner> %s" % self.name, "datasets", "merge", ['merge', 'append'])

        # Check all inputs that have been provided. It may be that for a single sweep'ed innput, multiple
        # input objects need to be added in case that one parameter of the sweep is to be grouped.
        inp_ids = r.findall('input')
        if not inp_ids:
            raise SpecificationError, "<combiner> '%s': need at least one <input> tag" % self.name

        self.axis_label = {}  # to replace the implicit label based on the value synopsis
        self.axis_unit = {}   # to replace the implicit label unit that comes with the value 
        self.inp_names = []
        suffix = ""
        for inp in inp_ids:
            if sweep_regexp != None:
                # If we just append all sweep suffixes of all input elements, the name
                # can become very long - too long to be stored in the "data origin"
                # column of the output table. Because the sweep suffixes of this name
                # will not be evaluated another time, we can replace them with 
                # their hash value (which will/should be unique!).
                if sweep_regexp.has_key(inp.text):
                    # Is there a faster way to do a regexp match on all values of the all_nodes dictionary?
                    for k in all_nodes.iterkeys():
                        if sweep_regexp[inp.text].search(k):
                            self.inp_names.append(k)
                            suffix += sweep_idx(k) + pb_sweep_suffix
                else:
                    # Not all inputs need to be found in the inputname-to-sweepname map!
                    if not all_nodes.has_key(inp.text):
                        raise SpecificationError, "<combiner> '%s': <input> '%s' is not defined" % (self.name, inp.text)
                    self.inp_names.append(inp.text)                
                suffix = suffix[:-1]
            else:
                # no sweeps at all
                if not all_nodes.has_key(inp.text):
                    raise SpecificationError, "<combiner> '%s': <input> '%s' is not defined" % (self.name, inp.text)
                self.inp_names.append(inp.text)
            if do_debug():
                print "#* DEBUG: adding <input>", inp.text
            self.axis_label[self.inp_names[-1:][0]] = mk_label(inp.get("axislabel"), all_nodes)
            self.axis_unit[self.inp_names[-1:][0]] = mk_label(inp.get("axisunit"), all_nodes)

        if sweep_regexp != None:
            # This does generate a unique name for this object. However, further sweep
            # processing won't be possible (but probably not desired, anyway).
            self.name += pb_sweep_suffix + str(hash(self))

        # sorting is necessary to bring all sweep permutations in the same order
        if self.sweep_group:
            self.inp_names.sort()

        # Parameter values which are explicitiely removed.
        omit_list = []
        omit_nodes = r.findall('omit')
        for n in omit_nodes:
            name = n.text
            if not name:
                raise SpecificationError, "<combiner> '%s': <omit> has to provide a name" % self.name
            inp  = n.get("input")
            if inp:
                omit_list.append((name, inp))
            else:
                for inp in self.inp_names:
                    omit_list.append((name, inp))

        # Determine the data that we get from the input elements which we will pass up to the next
        # element. Remove duplicate parameter entries if the user wants this..
        self.param_infos = []
        self.result_infos = []
        self.value_name_map = {}
        self.value_op_map = {}

        if self.datasets == "merge":
            self._setup_merge(db, all_nodes, omit_list, self.sweep_group)
        elif self.datasets == "append":
            self._setup_append(db, all_nodes, omit_list, self.sweep_group)

        self.src_tables = {}
        for n in self.inp_names:
            self.src_tables[n] = all_nodes[n].get_table_name()

        self.have_shutdown = False
        return

    def _setup_merge(self, db, all_nodes, omit_list, sweep_group = None):
        """Give internal names to the different parameter and result data streams, and create the output table."""
        vnames = []
        idx = 0
        for n in self.inp_names:
            for p in all_nodes[n].get_param_info():
                new_pname = p[0]
                if not self.show_params or (p[0],n) in omit_list:
                    continue
                
                while new_pname in vnames:
                    if self.hide_double_params:
                        new_pname = None
                        break
                    # Need to create a new SQL name to avoid collision of the same names in the
                    # single query table.
                    idx += 1
                    new_pname = p[0] + '_' + str(idx)
                if new_pname == None:
                    continue
                vnames.append(new_pname)                
                self.value_name_map[new_pname] = p[0]

                # When merging datasets, add source name for differentation, but only once
                new_pname_ext = p[1]
                if len(self.inp_names) > 1 and new_pname_ext[-1:] != ">":                    
                    new_pname_ext += '|' + n 

                p = [new_pname, new_pname_ext, p[2], p[3], p[4], p[5], p[6]]
                if self.axis_unit[n] is not None:
                    p[4] = self.axis_unit[n]
                if self.axis_label[n] is not None:
                    p[5] = self.axis_label[n]
                self.param_infos.append(p)
                self.value_op_map[p[0]] = n

            for r in all_nodes[n].get_result_info():
                new_rname = r[0]
                if (r[0],n) in omit_list:
                    continue

                # Result values are never dropped because of duplicates!
                # However, need to create a new SQL name to avoid collision of the same names in the
                # single query table.
                while new_rname in vnames:
                    idx += 1
                    new_rname = r[0] + '_' + str(idx)
                vnames.append(new_rname)
                self.value_name_map[new_rname] = r[0]

                # When merging datasets, add source name for differentation, but only once
                new_rname_ext = r[1]
                if len(self.inp_names) > 1 and new_rname_ext.find('|') == -1:
                    # add source name, but only once
                    new_rname_ext += '|' + n 

                r = [new_rname, new_rname_ext, r[2], r[3], r[4], r[5], r[6]]
                if self.axis_unit[n] is not None:
                    r[4] = self.axis_unit[n]
                if self.axis_label[n] is not None:
                    r[5] = self.axis_label[n]

                if len(self.param_infos) == 0 and self.mkparam:
                    # This result vector becomes a parameter vector.
                    self.param_infos.append(r)
                else:
                    self.result_infos.append(r)
                self.value_op_map[r[0]] = n

        # Now create the output table.
        table_entries = []
        for j in (self.param_infos, self.result_infos):
            for i in j:
                table_entries.append((i[0], i[3]))
        try:
            self.tgt_table = create_query_table(db, table_entries)        
        except SpecificationError, error_msg:
            print "#* ERROR in <input> '%s':" % n
            print "  ", error_msg
            exit(1)

        return

    def _setup_append(self, db, all_nodes, omit_list, sweep_group = None):
        """Prepare combination of <input>s by appending them. We need to make sure that all
        <input>s provide the same parameter and result values."""
        
        vnames = []
        inp_idx = 0
        for n in self.inp_names:
            for p in all_nodes[n].get_param_info():
                pname = p[0]

                if not self.show_params or (pname,n) in omit_list:
                    continue
                
                if inp_idx > 0:
                    if pname not in vnames:
                        raise SpecificationError, "<combiner> %s: parameter '%s' of <input> '%s' does not match." \
                              % (self.name, pname, n)
                    continue

                vnames.append(pname)
                self.value_name_map[pname] = p[0]
                p = [p[0], p[1], p[2], p[3], p[4], p[5], p[6]]
                self.param_infos.append(p)

                self.value_op_map[p[0]] = n

            for r in all_nodes[n].get_result_info():
                rname = r[0]

                if (rname,n) in omit_list:
                    continue

                if inp_idx > 0:
                    if rname not in vnames:
                        raise SpecificationError, "<combiner> %s: result '%s' of <input> '%s' does not match." \
                              % (self.name, rname, n)
                    continue

                vnames.append(rname)
                self.value_name_map[rname] = r[0]
                r = [r[0], r[1], r[2], r[3], r[4], r[5], r[6]]
                self.result_infos.append(r)

                self.value_op_map[r[0]] = n

            inp_idx += 1
            
        # Now create the output table.
        table_entries = []
        for j in (self.param_infos, self.result_infos):
            for i in j:
                table_entries.append((i[0], i[3]))
        try:
            self.tgt_table = create_query_table(db, table_entries)        
        except SpecificationError, error_msg:
            print "#* ERROR in <input> '%s':" % n
            print "  ", error_msg
            exit(1)

        return

    def shutdown(self, db):
        if not self.have_shutdown:
            drop_query_table(db, self.tgt_table)
            for n in self.inp_names:
                self.all_nodes[n].shutdown(db)
            self.have_shutdown = True
        return
        
    def perform_query(self, db):
        """The combiner objects retrieve the data from the database and generate output data
        in an internal, generic format."""
        if do_profiling():
            t0 = time.clock()

        if self.have_performed_query:
            if do_profiling():
                t0 = time.clock() - t0
                self.prof_data['perform_query'].append(t0)
            return
        self.have_performed_query = True

        # Let the operators do their work.
        for n in self.inp_names:
            self.all_nodes[n].perform_query(db)
            # check for updated result filter information
            for f in self.all_nodes[n].update_filters():
                self.updated_filters.append(f)
                for ri in self.result_infos:
                    if ri[6].count(f[0]) > 0:
                        ri[6] = ri[6].replace(f[0], f[1])

        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['perform_query'].append(t0)
        return

    def _append_datasets(self, crs, target_table):
        """Appending is more simple than merging: just go through the <input>s one by one
        and store the affected columns in the ouptput table."""
        col_header = "%s," % (pb_origin_colname)
        extcol_header ="%s,%s," % (pb_runidx_colname, pb_runorder_colname)
        col_str = ""
        for pi in self.param_infos:
            col_str += "%s," % pi[0]
        for ri in self.result_infos:
            col_str += "%s," % ri[0]

        sql_head = "SELECT %s " % (col_header + extcol_header + col_str[:-1])

        for n in self.inp_names:
            sqlexe(crs, sql_head + "FROM " + self.src_tables[n])
            db_rows = crs.fetchall()
            nim = build_name_idx_map(crs)

            for row in db_rows:
                val_str = "'%s'," % self.name
                if row[nim[pb_runidx_colname]] is not None:
                    val_str += "%s,%s," % (row[nim[pb_runidx_colname]], row[nim[pb_runorder_colname]])
                    cols = col_header + extcol_header + col_str[:-1]
                else:
                    cols = col_header + col_str[:-1]
                
                for pi in self.param_infos:
                    val_str += get_sql_contents(pi, row[nim[pi[0].lower()]]) + ","
                for ri in self.result_infos:
                    val_str += get_sql_contents(ri, row[nim[ri[0].lower()]]) + ","
                sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (target_table, cols, val_str[:-1]),
                       "#* DEBUG: <combiner>.store_data: %s storing data:" % (self.name))

        return

    def _merge_datasets(self, crs, target_table):
        # Merge the different tables into the single output table. We do this
        # on a row-by-row basis. Are other ways possible?
        # All result values of all input tables will be stored in the output
        # table. The parameter values will be filtered according to the content
        # of the 'parameter' attribute in the query description. In case of duplicates,
        # the names have been redefined.

        # Can not propagate run-index here.
        sql_cmd = "SELECT " 
        for pi in self.param_infos:
            sql_cmd += self.src_tables[self.value_op_map[pi[0]]] + '.' + self.value_name_map[pi[0]] + ','
        for ri in self.result_infos:
            sql_cmd += self.src_tables[self.value_op_map[ri[0]]] + '.' + self.value_name_map[ri[0]] + ','
        sql_cmd = sql_cmd[:-1] + " FROM "
        # Adding the FROM clause even when all tables are already specified became
        # necessary with PostgreSQL 8.x.
        for t in self.src_tables.itervalues():
            sql_cmd += t + ","
        sql_cmd = sql_cmd[:-1]
        
        if len(self.src_tables) > 1:
            sql_cmd += " WHERE "

            # For 2 input streams, this clause can be a simple inp1.id=inp2.id. However, for
            # 3 or more input streams, this doesn't work any longer: inp1.id=inp2.id=inp3.id
            # is invalid SQL. Instead, we need to say 'inp1.id=inp2.id AND inp1.id=inp3.id AND inp2.id=inp3.id'
            n_inp = len(self.inp_names)
            for i in range(n_inp-1):
                for j in range(i+1,n_inp):
                    sql_cmd +=  "%s.%s=%s.%s AND " % (self.src_tables[self.inp_names[i]], pb_dataidx_colname,
                                                      self.src_tables[self.inp_names[j]], pb_dataidx_colname)            
            sql_cmd = sql_cmd[:-4]
        sqlexe(crs, sql_cmd, "#* DEBUG: <combiner>.store_data: gathering data")
        db_rows = crs.fetchall()        

        col_str = "%s," % (pb_origin_colname)
        for pi in self.param_infos:
            col_str += pi[0] + ','
        for ri in self.result_infos:
            col_str += ri[0] + ','
        col_str = col_str[:-1]

        for row in db_rows:
            val_str = "'%s'," % (self.name)
            
            idx = 0
            for pi in self.param_infos:
                val_str += get_sql_contents(pi, row[idx]) + ","
                idx += 1
            for ri in self.result_infos:
                val_str += get_sql_contents(ri, row[idx]) + ","
                idx += 1

            sqlexe(crs, "INSERT INTO %s (%s) VALUES (%s)" % (target_table, col_str, val_str[:-1]),
                   "#* DEBUG: <combiner>.store_data: %s storing data:" % (self.name))

        return
    
    def store_data(self, db, table_name = None):
        # Gather the data of all operators in different tables.
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

        for n in self.inp_names:
            self.all_nodes[n].store_data(db)

        crs = db.cursor()

        if self.datasets == "merge":
            self._merge_datasets(crs, output_table)
        elif self.datasets == "append":
            self._append_datasets(crs, output_table)

        db.commit()
        crs.close()
        
        if do_profiling():
            t0 = time.clock() - t0
            self.prof_data['store_data'].append(t0)
        return
    
    def remove_data(self, db):
        crs = db.cursor()
        sqlexe(crs, "DELETE FROM %s" % self.tgt_table)
        db.commit()
        crs.close()
        return
    
    def get_param_info(self):
        return self.param_infos
    def get_next_paramset(self):
        return None
    def get_result_info(self):
        return self.result_infos
    def update_filters(self):
        return self.updated_filters
    def get_next_resultset(self):
        return None

        
class parameter:
    def __init__(self, node, db, all_nodes, sweep_filter = None, idx = -1):
        global pb_sweep_suffix
        crs = db.cursor()

        # get the optional id of this query parameter
        self.name = node.get('id')
        self.all_nodes = all_nodes
        self.type = "parameter"
        
        # get the parameter value name (in the experiment)
        val_node = node.find("value")
        if val_node is None and val_node.text is None:
            raise SpecificationError, "no <value> specified for <parameter>" 
        self.p_name = val_node.text
        if do_debug():
            print "#* DEBUG: adding parameter filter '%s'" % self.p_name
        alias = mk_label(get_attribute(val_node, self.p_name, 'alias', self.p_name, None),
                         all_nodes)

        sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s AND NOT is_result", None, (self.p_name, ))
        if crs.rowcount == 0:
            raise SpecificationError, "<value> '%s' is not a parameter in the specified experiment" % self.p_name
        nim = build_name_idx_map(crs)
        db_row = crs.fetchone()
        self.val_type = get_value_type(db_row, nim)
        self.is_constant = False
        if db_row[nim['only_once']] > 0:
            self.is_constant = True
        p_unit = db_row[nim['data_unit']]
        if not p_unit:
            p_unit = ""
        crs.close()

        self.showstyle = get_attribute(node, self.p_name, 'style', 'full',
                                       ('full', 'content', 'value', 'reverse', 'plain',
                                        'true', 'false', 'on_off', 'yes_no', 'toggle',
                                        'with_without', 'enabled_disabled'))

        if  get_attribute(node, self.p_name, 'unit', 'yes', ('yes', 'no')) == "no":
            p_unit = ""
            
        self.showdata = not self.is_constant        
        if node.find('filter') is not None and not self.is_constant:
            # If there's an explicit filter for a non-constant parameter
            # we need to provide the data
            self.showdata = True
        self.showfilter = self.is_constant
        valid_show_vals = ('all', 'data', 'filter', 'title', 'nothing', 'auto')
        att = node.get('show')
        if att:
            val = lower(att)
            if not val in valid_show_vals:
                raise SpecificationError, "<parameter> %s: invalid attribute value %s for 'show'" \
                      % (self.p_name, att)
            if val == "nothing":
                self.showdata = False
                self.showfilter = False
            elif val == "filter":
                self.showdata = False
                self.showfilter = True
            elif val == "all":
                self.showdata = True
                self.showfilter = True
            elif val == "data":
                self.showdata = True
                self.showfilter = False
            elif val == "auto":
                # leave everything as is
                pass
        if do_debug():
            print "#* DEBUG: %s showdata=%s showfilter=%s showstyle=%s" \
                  % (self.p_name, self.showdata, self.showfilter, self.showstyle)
            
        self.sql_filter = None
        self.filter_str = ""
        if sweep_filter is None:
            if node.find('filter') is not None:
                self.sql_filter = self._parse_filter(node, self.p_name, alias, p_unit)
            elif self.is_constant:
                if self.showdata:
                    # default filter for only-once parameters is "show all non-NULL entries"
                    self.sql_filter = "%s IS NOT NULL" % self.p_name
                else:
                    if be_verbose():
                        print "#* WARNING: <parameter> '%s' with 'occurrence=once' without <filter> and not" % self.p_name
                        print "            showing its data does not make sense."
                # Special case: no filter condition was specified, but the user wants to see the content
                # of the parameter in the plot. This does only make sense if the parameter has a single
                # content for all datasets! We set the filter string to '?' to mark it - it
                # will be set after we have all datasets available.
                if self.showfilter:
                    if self.showstyle == "full":
                        self.filter_str = "%s = %s" % (alias, pb_filter_str)
                    elif self.showstyle == "content":
                        self.filter_str = pb_filter_str
                    elif self.showstyle == "reverse":
                        self.filter_str = "%s %s" % (pb_filter_str, alias)
                    elif self.showstyle == "plain":
                        self.filter_str = "%s %s" % (alias, pb_filter_str)
                    elif self.showstyle == "value":
                        self.filter_str = "%s" % (alias)
                    elif self.showstyle in ("true", "false"):
                        self.filter_str = self.showstyle
                    else:
                        # Default for unknown value of "showfilter" (otherwise, no
                        # output at all would be generated).
                        if be_verbose():
                            print "#* WARNING: unsupported showstyle attribute '%s' in filter for %s" % (self.showstyle, alias)
                        self.filter_str = "%s = %s" % (alias, pb_filter_str)
                    # TODO: we would like to have better support for boolean variables
                    # here - like "with_without", "on_off" (see below)
        else:
            self.sql_filter = self._parse_filter(sweep_filter, self.p_name, alias, p_unit)
            self.name += pb_sweep_suffix + str(idx)

        # SQL name, verbose name, pb and sql data unit, physical unit, synopsis and filter
        self.param_info = [self.p_name, alias, db_row[2], db_row[3], db_row[4], db_row[6], self.filter_str]
        
        return
           
    def _parse_filter(self, f_node, p_name, p_alias, p_unit):
        "Recursively transform an XML <filter> expression into an SQL WHERE condition."
        bool_expr = get_attribute(f_node, "<parameter> '%s'" % self.name, 'boolean', 'AND',
                                  ("AND", "OR", "NOT", "and", "or", "not")).upper()
            
        subfilters = []
        sql_filter = ""
        cond_cnt = 0
        partial_filter = ""        
        
        filter_nodes = f_node.findall('filter')
        if filter_nodes:
            for f in filter_nodes:
                # go further down the tree
                sql_f = self._parse_filter(f, p_name, p_alias, p_unit)
                if len(sql_f) > 0:
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    self.filter_str = "%s%s " % (self.filter_str, bool_expr)
        else:
            # this is a leaf filter node, which however may contain multiple conditions!
            f_alias = f_node.get("alias")
            
            found_condition = True
            while found_condition:
                found_condition = False

                cond = f_node.find('all')
                if cond is not None:
                    # match everything - not a effective filter!
                    sql_f = "%s IS NULL OR %s IS NOT NULL" % (p_name, p_name)
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('null')
                if cond is not None:
                    sql_f = "%s IS NULL" % p_name
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    if self.showfilter:
                        if not f_alias:
                            if self.showstyle == "full":
                                partial_filter += "%s = NULL %s " % (p_alias, bool_expr)
                            elif self.showstyle == "content":
                                # NULL content is not shown at all - there is nothing to show...
                                partial_filter += "''"
                        else:
                            partial_filter += f_alias
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('notnull')
                if cond is not None:
                    sql_f = "%s IS NOT NULL" % p_name
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s != NULL %s " % (p_alias, bool_expr)
                        else:
                            partial_filter += f_alias
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('lesser')
                if cond is not None:
                    c = cond.text
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    cond_str = get_quoted_value(c, self.val_type)
                    sql_f = "%s < %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s < %s%s %s " % (p_alias, cond_str, p_unit, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('lessequal')
                if cond is not None:
                    c = cond.text
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    cond_str = get_quoted_value(c, self.val_type)
                    sql_f = "%s <= %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s <= %s%s %s " % (p_alias, cond_str, p_unit, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('greater')
                if cond is not None:
                    c = cond.text
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    cond_str = get_quoted_value(c, self.val_type)
                    sql_f = "%s > %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s > %s%s %s " % (p_alias, cond_str, p_unit, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('greaterequal')
                if cond is not None:
                    c = cond.text                    
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    cond_str = get_quoted_value(c, self.val_type)
                    sql_f = "%s >= %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s >= %s%s %s " % (p_alias, cond_str, p_unit, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('equal')
                if cond is not None:
                    c = cond.text
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    cond_str = get_quoted_value(c, self.val_type)
                    sql_f = "%s = %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            if self.showstyle == "full":
                                partial_filter += "%s = %s%s %s " % (p_alias, cond_str, p_unit, bool_expr)
                            elif self.showstyle == "plain":
                                partial_filter += "%s %s%s %s " % (p_alias, cond_str, p_unit, bool_expr)
                            elif self.showstyle == "content":
                                partial_filter += " %s%s %s " % (cond_str, p_unit, bool_expr)
                            elif self.showstyle == "reverse":
                                partial_filter += " %s%s %s %s" % (cond_str, p_unit, p_alias, bool_expr)
                            elif self.showstyle == "value":
                                partial_filter += " %s %s" % (p_alias, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)

                cond = f_node.find('notequal')
                if cond is not None:
                    c = cond.text                    
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    cond_str = get_quoted_value(c, self.val_type)
                    sql_f = "%s != %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            if self.showstyle == "full":
                                partial_filter += "%s != %s%s %s " % (p_alias, cond_str, p_unit, bool_expr)
                            elif self.showstyle == "content":
                                partial_filter += " not %s%s %s " % (cond_str, p_unit, bool_expr)
                            elif self.showstyle == "value":
                                partial_filter += " %s %s" % (p_alias, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('bool')
                if cond is not None:
                    c = cond.text
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    c = lower(c)
                    if self.val_type != "bool":
                        raise SpecificationError, "parameter %s needs to be a boolean type for 'bool' <filter>" % p_name
                    if c not in ("true", "false"):
                        raise SpecificationError, "invalid content %s for 'bool' <filter>" % c
                    if c == "true":
                        cond_str = "IS TRUE"
                    else:
                        cond_str = "IS FALSE"
                    sql_f = "%s %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            if self.showstyle == "full":
                                partial_filter += "%s %s  %s " % (p_alias, cond_str, bool_expr)
                            elif self.showstyle == "content" and c == "true":
                                partial_filter += " %s %s " % (p_alias, bool_expr)
                            elif self.showstyle == "on_off":
                                if c == "true":
                                    partial_filter += " %s on %s " % (p_alias, bool_expr)
                                else:
                                    partial_filter += " %s off %s " % (p_alias, bool_expr)
                            elif self.showstyle == "with_without":
                                if c == "true":
                                    partial_filter += " with %s %s " % (p_alias, bool_expr)
                                else:
                                    partial_filter += " without %s %s " % (p_alias, bool_expr)
                            elif self.showstyle == "enabled_disabled":
                                if c == "true":
                                    partial_filter += " %s enabled %s " % (p_alias, bool_expr)
                                else:
                                    partial_filter += " %s disabled %s " % (p_alias, bool_expr)
                            elif self.showstyle == "yes_no":
                                if c == "true":
                                    partial_filter += " %s %s " % (p_alias, bool_expr)
                                else:
                                    partial_filter += " no %s %s " % (p_alias, bool_expr)
                            elif self.showstyle == "toggle":
                                if c == "true":
                                    partial_filter += " %s %s " % (p_alias, bool_expr)
                                else:
                                    partial_filter += " %s " % (bool_expr)
                            else:
                                # 'true' or 'false'
                                if self.showstyle == c:
                                    partial_filter += " %s %s " % (p_alias, bool_expr)
                                else:
                                    # dummy to keep the number of label constant
                                    partial_filter += " "
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('contain')
                if cond is not None:
                    c = cond.text                    
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    if self.val_type != "string":
                        raise SpecificationError, "parameter %s needs to be a string type for 'contain' <filter>" % p_name
                    cond_str = "IN '%s'" % c
                    sql_f = "%s %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s %s %s " % (p_alias, cond_str, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)                

                cond = f_node.find('match')
                if cond is not None:
                    c = cond.text                    
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    if self.val_type != "string":
                        raise SpecificationError, "parameter %s needs to be a string type for 'match' <filter>" % p_name
                    cond_str = "LIKE '%s'" % c
                    sql_f = "%s %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s %s %s" % (p_alias, cond_str, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)

                cond = f_node.find('regexp')
                if cond is not None:
                    c = cond.text                    
                    if self.all_nodes.has_key(c): c = self.all_nodes[c].get_content()
                    if self.val_type != "string":
                        raise SpecificationError, "parameter %s needs to be a string type for 'regexp' <filter>" % p_name
                    cond_str = "~ '%s'" % c
                    sql_f = "%s %s" % (p_name, cond_str)
                    if self.showfilter:
                        if not f_alias:
                            partial_filter += "%s %s %s" % (p_alias, cond_str, bool_expr)
                        else:
                            partial_filter += f_alias
                    subfilters.append("("  + sql_f + ") " + bool_expr + " ")
                    found_condition = True
                    f_node.remove(cond)

                if found_condition:
                    cond_cnt += 1
            
        if do_debug():
            print "#* DEBUG: subfilters ", subfilters
        for f in subfilters:
            sql_filter += f
        if do_debug():
            print "#* DEBUG: sql_filter ", sql_filter

        if cond_cnt == 1:
            # for a single condition, we don't need parenthesis
            partial_filter = partial_filter.strip("()")
        if cond_cnt > 1:
            partial_filter = partial_filter.strip() + ")"
        self.filter_str += partial_filter
        self.filter_str = self.filter_str[:-(len(bool_expr)+1)]
        
        return sql_filter[:rfind(sql_filter, " ", 0, -1)]
    
    def get_name(self):
        return self.name

    def get_sql_filter(self):
        return self.sql_filter

    def get_param_info(self):
        return self.param_info

    def get_val_type(self):
        return self.val_type

    def print_profiling(self):
        "dummy function"
        return

class fixed:
    def __init__(self, node, name=None, value=None):
        self.type = "fixed"
        if node is not None:
            self.name=node.get('id')
            if not self.name:
                raise SpecificationError, "each <fixed> value needs an 'id' attribute"
            value = node.findtext('content')
        else:
            self.name = name

        if value is None:
            raise SpecificationError, "each <fixed> value needs a non-empty <content>"

        self.content = value
        return

    def get_name(self):
        return self.name
                  
    def get_content(self):
        return self.content

    def print_profiling(self):
        "dummy function"
        return

class run:
    def __init__(self, node, db, all_nodes):
        global pb_months
        self.type = "run"
        
        crs = db.cursor()
        
        # get the optional id of this query run selection
        self.name = node.get('id')
        if not self.name:
            raise SpecificationError, "<run>: required attribute 'id' is missing."

        # Is this an 'include' or 'exclude' type of specification?
        include_runs = True
        att = node.get('mask')
        if att:
            if not att in ("include", "exclude"):
                raise SpecificationError, "<run> '%s': invalid content for attribute 'mask'"
            if att == "exclude":
                include_runs = False

        # does a run need to match *all* filters ('and'), or any single one ('or')?
        match_all = True
        att = node.get('boolean')
        if att:
            if not att in ("and", "or"):
                raise SpecificationError, "<run> '%s': invalid content for attribute 'boolean'"
            if att == "or":
                match_all = False        

        # get a list of all available runs for this experiment
        sqlexe(crs, "SELECT index FROM run_metadata WHERE active = 't'")
        nim = build_name_idx_map(crs)
        all_runs = {}
        all_rows = crs.fetchall()
        i = 0
        for r in all_rows:
            # XXX Are the elements of this lists already 'int's?
            i = int(r[nim['index']])
            all_runs[i] = True
        max_idx = i        

        n_filters = 0

        # filter by run index
        filter_indices = {} # map index of run-to-be-included to 'True' or 'False'
        
        run_filters = []        
        idx_nodes = node.findall('index')
        for n in idx_nodes:
            idx = n.text
            if all_nodes.has_key(idx):
                idx = all_nodes[idx].get_content()
            run_filters.extend(idx.split(','))
        try:
            for f in run_filters:
                n_filters += 1
                if f.startswith('...'):
                    # add all runs up to the given index
                    idx = int(f[3:])
                    for i in range(idx):
                        if all_runs.has_key(i):
                            filter_indices[i] = True
                elif f.endswith('...'):
                    # add all runs up from the given index
                    idx = int(f[:-3])
                    for i in range(idx, max_idx+1):
                        if all_runs.has_key(i):
                            filter_indices[i] = True
                elif f.count('-') == 1:
                    # add a range of indexes
                    idx_range = f.split('-')
                    idx_low = int(idx_range[0])
                    idx_up  = int(idx_range[1])
                    for i in range(idx_low, idx_up+1):
                        if all_runs.has_key(i):
                            filter_indices[i] = True
                else:
                    # add just the given index
                    idx = int(f)
                    if all_runs.has_key(idx):
                        filter_indices[idx] = True
                    else:
                        print "#* WARNING: <run> '%s' lists non-existing run <index> '%d' (ignored)" % (self.name, idx)
        except ValueError:
            raise SpecificationError, "<run> '%s': invalid run <index> specification '%s'" % (self.name, f)

        # filter by 'created' and 'performed' timestamp
        for stamp in ('created', 'performed'):
            sql_cmd = "SELECT index FROM run_metadata WHERE ("
            nodes = node.findall(stamp)
            for n in nodes:
                n_filters += 1

                from_time = n.findtext('from')
                if all_nodes.has_key(from_time):
                    from_time = all_nodes[from_time].get_content()
                to_time = n.findtext('to')
                if all_nodes.has_key(to_time):
                    to_time = all_nodes[to_time].get_content()

                time_stamp = [None, None]
                time_elmt = ['from', 'to']
                for i in range(len(time_stamp)):
                    stamp_node = n.find(time_elmt[i])
                    if not stamp_node is None:
                        date_node = stamp_node.find('date')
                        if not date_node is None:
                            day = date_node.findtext('day')
                            if day is None:
                                if time_elmt[i] == 'from':
                                    day = "1"
                                else:
                                    day = "31"
                            month = date_node.findtext('month')
                            if month is None:
                                if time_elmt[i] == 'from':
                                    month = pb_months[0]
                                else:
                                    month = pb_months[11]
                            else:
                                try:
                                    month = int(month) - 1
                                except ValueError:
                                    # Not an int, but a string! Check if valid.
                                    try:
                                        month = pb_months.index(lower(month))                                        
                                    except AttributeError:
                                        raise SpecificationError, "<run> '%s': invalid month '%s'" % (self.name, month)
                                try:
                                    month = pb_months[month]
                                except IndexError:
                                    raise SpecificationError, "<run> '%s': invalid month '%s'(1..12)" % (self.name, str(month))
                            year = date_node.findtext('year')
                            if year is None:
                                year = get_current_year()
                            else:
                                try:
                                    y = int(year)
                                except ValueError:
                                    raise SpecificationError, "<run> '%s': invalid year '%s'" % (self.name, year)
                            time_stamp[i] = "%s-%s-%s" % (day, month, year)
                            
                        time_node = stamp_node.find('time')
                        if not time_node is None:
                            # What about time zones?
                            hour = date_node.findtext('hour')
                            minute = date_node.findtext('minute')
                            second = date_node.findtext('second')
                            if hour is None or minute is None:
                                raise SpecificationError, "<run> '%s': invalid <time> (need hour and minute)" % self.name
                            if second is None:
                                second = "00"
                            ts = "%s:%s:%s" % (hour, minute, second)
                            if time_stamp[i] is None:
                                time_stamp[i] = ts
                            else:
                                time_stamp[i] += " "+ts

                if time_stamp[0]:
                    sql_cmd += "%s >= '%s'" % (stamp, time_stamp[0])
                    if to_time:
                        sql_cmd += " AND "
                if time_stamp[1]:
                    sql_cmd += "%s <= '%s'" % (stamp, time_stamp[1])
                sql_cmd += ") OR ("
                if not (time_stamp[0] or time_stamp[1]):
                    raise SpecificationError, "<run> '%s': invalid <%s> specification: neither <from> or <to> specified." \
                    % (self.name, stamp)

            if nodes:
                # put this into try .. except to catch invalid date formats!
                try:
                    sqlexe(crs, sql_cmd[:-5], "#* DEBUG: filtering <run> by %s timestamp." % stamp)
                except psycopg.Error, error_msg:
                    print "#* ERROR with <run> '%s': database error when querying runs by date." % self.name
                    print "   Date was specified from: %s to: %s" % (from_time, to_time)
                    print "   SQL command was: ", sql_cmd
                    print "   Database error message:", error_msg
                    exit(2)
                nim = build_name_idx_map(crs)
                all_rows = crs.fetchall()

                # For match_all with previous filters already executed,
                # we first need to set all active indices to "False"; these indices
                # that also pass this filter will be set to True again. The ones that are still "False"
                # afterwards will be removed.
                perform_AND = match_all and (len(filter_indices) > 0)
                if perform_AND:
                    for key in filter_indices.keys():
                        filter_indices[key] = False

                for r in all_rows:
                    key = int(r[nim['index']])
                    if perform_AND:
                        if filter_indices.has_key(key):
                            filter_indices[key] = True
                    else:
                        filter_indices[key] = True

                if perform_AND:
                    for key in filter_indices.keys():
                        if not filter_indices[key]:
                            del filter_indices[key]

        for stamp in ('synopsis', 'description'):
            syn_desc_nodes = node.findall(stamp)
            sql_cmd = "SELECT index FROM run_metadata WHERE ("
            for n in syn_desc_nodes:
                # provided strings are used as regular expressions with SQL
                syn_desc = n.text
                if all_nodes.has_key(syn_desc):
                    syn_desc = all_nodes[syn_desc].get_content()
                sql_cmd += " %s~'%s' " % (stamp, clean_string(syn_desc)) # regular expression!
                if match_all:
                    sql_cmd += "AND"
                else:
                    sql_cmd += "OR "
            if syn_desc_nodes:
                n_filters += 1;
                try:
                    sqlexe(crs, sql_cmd[:-3] + ")", "#* DEBUG: filtering <run> by %s" % stamp)
                except psycopg.Error, error_msg:
                    print "#* ERROR with <run> '%s': database error when querying runs by %s." % (self.name, stamp)
                    print "   Database error message:", error_msg
                    exit(2)
                nim = build_name_idx_map(crs)
                all_rows = crs.fetchall()

                # see above for "peform_AND"
                perform_AND = match_all and (len(filter_indices) > 0)
                if perform_AND:
                    for key in filter_indices.keys():
                        filter_indices[key] = False

                for r in all_rows:
                    key = int(r[nim['index']])
                    if perform_AND:
                        if filter_indices.has_key(key):
                            filter_indices[key] = True
                    else:
                        filter_indices[key] = True

                if perform_AND:
                    for key in filter_indices.keys():
                        if not filter_indices[key]:
                            del filter_indices[key]

        if n_filters == 0:
            raise SpecificationError, "<run> '%s': need to define at least one filter condition." % self.name

        # Determine the subset of runs to use:
        self.run_indices = {}
        if include_runs:            
            self.run_indices.update(filter_indices)
        else:
            for k in all_runs.iterkeys():
                if not filter_indices.has_key(k):
                    self.run_indices[k] = True

        crs.close()
        return

    def get_name(self):
        return self.name

    def get_runs(self):
        return self.run_indices.keys()

    def print_profiling(self):
        "dummy function"
        return
