# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_input - Input data of one or more runs from an ASCII file
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
from pb_access import rdline

import sys
import xml
import re
import getopt
import os, stat
import time
import tempfile
import sre_constants
from os import F_OK, R_OK, getenv, access
from os.path import basename, realpath, getmtime
from time import localtime, strftime
from string import find, split, whitespace, lower, upper, strip, rstrip, maketrans, printable
from xml.etree import ElementTree
from random import seed, randint
from math import acos, asin, atan, atan2, ceil, cos, cosh, exp, fabs, \
     floor, fmod, hypot, ldexp, log, log10, pow, sin, sinh, sqrt, tan, tanh
from cmath import acosh, asinh, atanh
from linecache import getline, clearcache

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg


# classes
class parser_nodes:
    def __init__(self):
        self.nodes = []
        self.n_nodes = 0
        return
    

class input_parse:
    """Accepts a line of a data file, and checks if it triggers any (value) condition.
    If a condition was triggered, it can also be used to retrieve data from such lines."""
    def __init__(self, element_tree, parse_nodes, crs):
        """Initialization is done by passing an ElementTree reference to the definition
        (can be set_separation, named_location, explicit_location, tabular_location or fixed_value).
        Possible exception:
        - SpecificationError    the (XML) description for this value was invalid"""
        self.parse_cnt = 0
        self.trigger_cnt = 0
        self.only_once = False
        self.name = None
        self.filter = None
        self.update = {}             # parameter values of the set constituting an update filter

        # profiling information: one list of durations for each function to be profiled. For now,
        # only these two function are really of interest.
        self.prof_data = { 'check_trigger' : [], 'parse_data' : [] }

        return
    def check_trigger(self, fname, idx):
        """Check if the line 'idx' of 'fname' contains a trigger condition for this value. Has to 
        be called for each line of the input file. 'lines' contains all lines of the input file - 
        this is necessary to handle triggers that are not on the same line as the data.

        If 'True' is returned, it means that this object's
        'parse_data()' method has to be called for this line."""
        return False
    def parse_data(self, fname, idx):
        """Parse line 'idx' from fname for data suitable for this object. If data is found, it is 
        stored inside this object for later retrieval via 'get_data()'.
        Two exceptions can be raised by this method:
        - StoreDataset: A data set is complete and has to be stored in the database.
        - DataError: internal error, as the check_trigger() call should have
        determined that there is data.
        """
        return
    def get_trigger_count(self):
        """Return the number of events in which content was detected (via a call to check_trigger().
        '0' means that no content has been detected so far. """
        return self.trigger_cnt
    def get_parse_count(self):
        """Return the number of events in which content was parsed (via a call to parse_data().
        '0' means that no data has been parsed so far. """
        return self.parse_cnt
    def get_value_names(self):
        """Return a list of value names that this object processes."""
        return None
    def get_value_contents(self, reset = True):
        """Return a dictionary, indexed by value names and containing the textual representation
        of each value's data."""
        return None
    def get_update_values(self):
        """Return a dictionary, indexed by value names mapped to a string 'yes' or 'auto' which is
        this values update characteristic (see attribute 'update')."""
        return self.update
    def new_run(self):
        """Has to be called if data for a new run is parsed from the (same or a different) input file.
        If 'False' is returned, this object needs to store data for the old run before the new run
        can be started. This needs to be repeated (usually only once) as long as 'False' is returned.
        Otherwise, this object is prepared for the next run."""
        return True
    def print_profiling(self):
        """Print out the collected profiling data (number of calls, min/max/avg of processing time)."""

        print ""
        print "* profiling information for %s (name %s)" % (self.type, self.name)

        for k, v in self.prof_data.iteritems():
            print "  ", k
            print "   number of calls:", len(v)
            if len(v) > 0:
                print "   min. duration [ms] : %6.3f" % (min(v)*1000)
                print "   max. duration [ms] : %6.3f" % (max(v)*1000)
                sum = 0.0
                for t in v:
                    sum = sum + t
                print "   avg. duration [ms] : %6.3f" % (sum/len(v)*1000)
                print "   acc. duration [s]  : %6.3f" % sum


class derived_parameter(input_parse):
    def __init__(self, element_tree, parse_nodes, crs):
        input_parse.__init__(self, element_tree, parse_nodes, crs)
        
        self.eval_string = None
        self.nbr_params_ready = 0
        self.data_is_stored = False
        self.content = None
        self.parse_cnt = 0
        self.type = 'derived'
        self.valid_vals = None
        
        r = element_tree

        self.name = r.findtext('name')
        if not self.name:
            raise SpecificationError, "<name> tag missing in <derived_parameter>"

        sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (self.name, ))
        nim = build_name_idx_map(crs)
        if crs.rowcount == 1:
            db_row = crs.fetchone()
            self.is_numeric = db_row[nim['is_numeric']]
            self.only_once  = db_row[nim['only_once']]
            # also store this info globally
            is_numeric[self.name] = self.is_numeric
            only_once[self.name] = self.only_once
            # retrigger means that after data has been parsed and stored, it will trigger for new data
            self.retrigger = not self.only_once 
            if db_row[nim['valid_values']] != None:
                self.valid_vals = db_row[nim['valid_values']]
        else:
            raise SpecificationError, "<derived_parameter> for '%s': invalid value '%s'" %(self.name, self.name)

        self.store_set = False    # this value triggers storing a set
        att = get_attribute(r, "<named_location> %s" % self.name, "store_set", "no", ["yes", "no"])
        if att == 'yes':
            self.store_set = True

        att = get_attribute(r, "<derived_parameter> %s" % self.name, "update", "no",
                            ['yes', 'no', 'auto'])
        if att in ('yes', 'auto'):
            self.update[self.name] = att

        self.sticky = False
        att = get_attribute(r, "<derived_parameter> %s" % self.name, "retrigger", "auto",
                            ['yes', 'no', 'auto', 'sticky'])
        if att == 'yes':
            self.retrigger = True
        elif att == 'sticky':
            self.retrigger = True
            self.sticky = True
        elif att == 'no':
            self.retrigger = False

        # Build a dictionary of all parameters specified in this parse operation.
        # XXX We could store this globally if it is needed in other places!?
        self.parameters = {}
        for pn in parse_nodes:
            if pn.get_value_names(): # some parse nodes may return "None"!
                for vn in pn.get_value_names():
                    sqlexe(crs, "SELECT is_result FROM exp_values WHERE name = '%s'" % vn)
                    db_rows = crs.fetchall()
                    if len(db_rows) != 1:
                        raise SpecificationError, "<derived_parameter> '%s': invalid value name '%s'" \
                              % (self.name, vn)
                    if not db_rows[0][0]:
                        # not 'is_result' means 'is parameter"
                        if False and pb_debug:
                            print "DEBUG: <derived_parameter.init> adding parameter", vn
                        # It is possible that multiple parse nodes are defined for the same value name!
                        # Therefore, we store a list of parse nodes instead the parse node directly.
                        if not self.parameters.has_key(vn):
                            self.parameters[vn] = [pn]
                        else:
                            self.parameters[vn].append(pn)

        self.trigger_params = {}
        self.trigger_params_cnt = {}
        self.trigger_params_nodes = {}
        self.param_ready = {}
        self.nbr_params_once = 0
        self.nbr_params_multiple = 0

        # Prepare to calculate the content from other parameter values content
        term = r.findall('term')
        if len(term) > 1:
            raise SpecificationError, "<derived_parameter> '%s': at most a single <term> allowed" % self.name
        elif len(term) == 1:
            self.eval_name = r.get('id')
            # _build_eval_string() fills up trigger_params, too
            self.eval_string = self._build_eval_string(term[0])

            for p_name in self.trigger_params.iterkeys():
                self.param_ready[p_name] = False
                # The number of parameters that are needed to derive this parameter is the sum of all
                # differently named parameters, not of all instances of such parameters. We use the first
                # instance here to decide if the parameter is "only_once" or "multiple" - this characteristic
                # has to be consistent! 
                if self.parameters[p_name][0].only_once:
                    self.nbr_params_once += 1
                else:
                    self.nbr_params_multiple += 1
            self.nbr_params = self.nbr_params_once + self.nbr_params_multiple
            if self.nbr_params == 0:
                raise SpecificationError, "<derived_parameter> '%s': no parameter reference in <term>" % self.name

        # Another use of a derived parameter is to map the content of one parameter to another one
        self.mappings = {}
        self.map_regexp = {}

        map = None
        map = r.find('map')
        if map is not None:
            # get the name of the source parameter for the mapping
            p_name = map.get("value")
            if p_name is None:
                raise SpecificationError,  " <derived_parameter> '%s': <map> needs to have 'value' attribute set."\
                      % (self.name)
            if not self.parameters.has_key(p_name):
                raise SpecificationError,  " <derived_parameter> '%s':  content of 'value' attribute of <map>"\
                      " specifies unknown parameter '%s'." % (self.name, p_name)
            self.param_ready[p_name] = False
            if self.parameters[p_name][0].only_once:
                self.nbr_params_once = 1
            else:
                self.nbr_params_multiple = 1
            self.nbr_params = 1
            
            for m in map.findall('mapping'):
                c_in  = m.find('content_in')
                c_out = m.find('content_out')
                if c_in is None or c_out is None or len(c_in.text) == 0 or len(c_out.text) == 0:
                    raise SpecificationError, " <derived_parameter> '%s': <mapping> needs <content_in> and <content_out> elements."\
                          % self.name
                if not self.valid_vals is None:
                    if not c_out.text in self.valid_vals:
                        raise SpecificationError, " <derived_parameter> '%s': <content_out> '%s' is not <valid> content."\
                              % (self.name, c_out.text)

                if not self.trigger_params.has_key(p_name):
                    # new dictionary and list of regexps for the mapping of this parameter
                    self.mappings[p_name] = {}
                    self.map_regexp[p_name] = []
                    self.trigger_params[p_name] = True

                att = get_attribute(c_in, "<derived_parameter> %s" % self.name, "match", "literal",
                                    ['literal', 'regexp'])
                if att == "regexp":
                    regexp = re.compile(c_in.text)
                    self.map_regexp[p_name].append(regexp)
                    self.mappings[p_name][regexp] = c_out.text
                else:
                    self.mappings[p_name][c_in.text] = c_out.text

        return

    def check_trigger(self, fname, idx):
        """The trigger checks if all of the specified input parameters provide valid data. If yes, 
        new content for this value can be calculated/mapped with the input of these parameters. 
        After this initial content generation, it is checked if any parameter has *new* content to offer. 
        If this happens, this parameter does also create new data."""
        if pb_profiling:
            t0 = time.clock()

        rval = "nothing"
        if self.sticky and self.trigger_cnt > 0:
            # If this parameter was triggered once and is 'sticky', trigger again for every line.
            # Does only make sense with a multiple-occurrence parameter.
            return "parse"

        debug_trigger = False
        for p_name in self.trigger_params.iterkeys():
            # Each value can be parsed by more than one node. A derived parameter supports this,
            # but uses the first data that any of the parse nodes for a given value name provides.
            if pb_debug or debug_trigger:
                #print "DEBUG: derived.check_name", p_name, self.nbr_params_ready, self.nbr_params
                pass
            for p_obj in self.parameters[p_name]:
                trigger_cnt = p_obj.get_trigger_count()
                if pb_debug or debug_trigger:
                    #print "DEBUG: derived.check_trigger", trigger_cnt, self.trigger_params_cnt[(p_obj,p_name)]
                    pass
                
                if (p_obj.only_once and trigger_cnt == 1 and self.trigger_params_cnt[(p_obj,p_name)] == 0) \
                       or (not p_obj.only_once and trigger_cnt > self.trigger_params_cnt[(p_obj,p_name)]):
                    # security check!
                    if trigger_cnt > self.trigger_params_cnt[(p_obj,p_name)] + 1:
                        raise DataError, "parse count run away for parameter '%s'" % p_name
                    if not self.param_ready[p_name]:
                        self.nbr_params_ready += 1
                        self.param_ready[p_name] = True
                    self.trigger_params_cnt[(p_obj,p_name)] += 1
                    self.trigger_params_nodes[p_name] = p_obj
                    if pb_debug or debug_trigger:
                        #print "DEBUG: derived.check_ready", self.nbr_params_ready, self.nbr_params
                        pass
                    if self.nbr_params_ready == self.nbr_params:
                        self.nbr_params_ready = self.nbr_params_once
                        self.trigger_cnt += 1
                        rval = "parse"

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['check_trigger'].append(t0)
        return rval

    def parse_data(self, fname, idx):
        """This means calling get_value_contents(False) of all input parameters, and caculating
        the new data point. """
        if pb_profiling:
            t0 = time.clock()

        new_content = False
        rval = "nothing"
        if self.eval_string is not None:
            # using a <term> specification to generate content
            term = self.eval_string
            for p_name, key in self.trigger_params.iteritems():
                # A retriggered derived parameter may get 'None' here! This is not a problem,
                # just return the appropiate return value.
                param_content = self.trigger_params_nodes[p_name].get_value_contents(False)
                if param_content is None:
                    if pb_profiling:
                        t0 = time.clock() - t0
                        self.prof_data['parse_data'].append(t0)
                    return rval
                term = term.replace(key, param_content[p_name])
            if pb_debug:
                print "DEBUG: <derived_parameter.parse_data> evaluating term '%s'" % term
            self.content = eval(term)
            new_content = True
        else:
            # <map>ing content to create new content
            for p_name in self.trigger_params.iterkeys():
                # for now, self.trigger_params will contains exactly one key
                param_content = self.trigger_params_nodes[p_name].get_value_contents(False)
                if param_content is None:
                    if pb_profiling:
                        t0 = time.clock() - t0
                        self.prof_data['parse_data'].append(t0)
                    return rval
                for re in self.map_regexp[p_name]:
                    if re.search(param_content[p_name]):
                        self.content = self.mappings[val][re]
                        new_content = True
                        break
                # direct matches override regexps
                if self.mappings[p_name].has_key(param_content[p_name]):
                    self.content = self.mappings[p_name][param_content[p_name]]
                    new_content = True

        if new_content and not self.data_is_stored:
            # Is it an error if data is already stored?
            self.data_is_stored = True
            self.parse_cnt += 1
            if self.only_once:
                rval = "store_value"
            elif self.store_set:
                rval = "store_set"
                    
        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['parse_data'].append(t0)

        return rval

    def get_value_names(self):
        return [ self.name ]

    def get_value_contents(self, reset = True):        
        d = None
        if self.content is not None:
            d = { self.name:self.content }
            if not self.only_once and reset:
                self.content = None
            if self.retrigger:
                # allow to retrigger after data has been read
                self.data_is_stored = False
                # prepare for next call to 'check_trigger' to parse a value again.
                for p_name in self.trigger_params.iterkeys():
                    if self.parameters[p_name][0].only_once:
                        self.trigger_params_cnt[(self.trigger_params_nodes[p_name], p_name)] = 0
                    else:
                        self.param_ready[p_name] = False
        return d

    def new_run(self):
        self.data_is_stored = False
        self.parse_cnt = 0
        self.trigger_cnt = 0
        for p_name in self.trigger_params.iterkeys():
            for p_obj in self.parameters[p_name]:
                self.trigger_params_cnt[p_obj, p_name] = 0
        self.nbr_params_ready = 0
        for k in self.param_ready.iterkeys():
            self.param_ready[k] = False
        self.content = None
        return True

    def _build_eval_string(self, term):
        """Build a string that reflects the expression defined by the <term> description."""
        global pb_valid_funcs, pb_namesrc_sep
        constants = ('e', 'pi')

        t = term.find('fraction')
        if not t is None:
            divisor  = t.find('divisor')
            dividend = t.find('dividend')
            if dividend is None:
                raise SpecificationError, "<term> '%s': no <dividend> in <fraction>" % self.name
            if divisor is None:
                raise SpecificationError, "<term> '%s': no <divisor> in <fraction>" % self.name
            t_str = '('+self._build_eval_string(dividend)+')/('+self._build_eval_string(divisor)+')'
            return t_str
        t = term.find('difference')
        if not t is None:
            minuend = t.find('minuend')
            if minuend is None:
                raise SpecificationError, "<term> '%s': no <minuend> in <difference>" % self.name
            subtrahend  = t.find('subtrahend')
            if subtrahend is None:
                raise SpecificationError, "<term> '%s': no <subtrahend> in <difference>" % self.name
            t_str = '('+self._build_eval_string(minuend)+')-('+self._build_eval_string(subtrahend)+')'
            return t_str
        t = term.find('product')
        if not t is None:
            factors = t.findall('factor')
            if len(factors) == 0:
                raise SpecificationError, "<term> '%s': no <factor> in <product>" % self.name
            t_str = '('
            for f in factors:
                t_str += self._build_eval_string(f) + ')*('
            t_str = t_str[:-2]
            return t_str
        t = term.find('sum')
        if not t is None:
            summands = t.findall('summand')
            if len(summands) == 0:
                raise SpecificationError, "<term> '%s': no <summand> in <sum>" % self.name
            t_str = '('
            for s in summands:
                t_str += self._build_eval_string(s) + ')+('
            t_str = t_str[:-2]
            return t_str
        t = term.find('function')
        if not t is None:
            func = t.get('type')
            if not func:
                raise SpecificationError, "<term> '%s': <function> requires attribute 'type'" % self.name
            if not pb_valid_funcs.has_key(func):
                raise SpecificationError, "<term> '%s': Invalid <function> type '%s'" % (self.name, func)
            args = t.findall('argument')
            if len(args) != pb_valid_funcs[func]:
                raise SpecificationError, "<term> '%s': <function> '%s' requires %d <arguments> (found %d)" \
                      % (self.name, func, pb_valid_funcs[func], len(args))
            t_str = func + '('
            for a in args:
                t_str += self._build_eval_string(a) + ','
            t_str = t_str[:-1] + ')'
            return t_str
        t = term.find('parameter')
        if not t is None:
            #  One of the input values, either referenced via an alias or its name.
            p_name = t.text
            if not p_name:
                raise SpecificationError, "<term> '%s': <parameter> requires the name of a parameter" % self.name
            if not self.parameters.has_key(p_name):
                raise SpecificationError, "<term> '%s': unknown parameter '%s'" % (self.name, p_name)
            p_key = pb_namesrc_sep + p_name + pb_namesrc_sep
            if pb_debug:
                print "DEBUG <derived_parameter>: adding trigger param %s" % p_name
            self.trigger_params[p_name] = p_key
            for p_obj in self.parameters[p_name]:
                self.trigger_params_cnt[p_obj,p_name] = 0
            return p_key
        
        # If we get here, we have a terminal symbol. This can either be an internal constant (see
        # tuple 'constants', a 'fixed_value' (defined in the query) or a number
        t = term.find('constant')
        if t is None:
            # XXX give the name of the element in question!
            raise SpecificationError, "Invalid element in <term> '%s'" % self.name
        # XXX This test gets confused by stray blanks etc.
        #if term.text:
        #    raise SpecificationError, "<term> '%s': <term> must not contain any text data, but only other elements" \
        #          % self.name
        sym = t.text
        if not sym:
            raise SpecificationError, "<term> '%s': <constant> has no content" % self.name
        # Is it an internal constant?
        if sym in constants:
            return sym
        # Is it a valid number?
        try:
            f = float(sym)
            return sym  # it's a valid number
        except ValueError:
            pass
        # Is t a fixed value?
        # XXX Is all_nodes used anywhere else then here?
        if self.all_nodes.has_key(sym) and isinstance(self.all_nodes[sym], fixed):
            return self.all_nodes[sym].get_content()
        # It's something invalid!
        raise SpecificationError, "<derived_parameter> '%s': invalid symbol '%s' in <constant>" % (self.name, sym)
        return 


class split_location(input_parse):
    def __init__(self, element_tree, parse_nodes, crs):
        input_parse.__init__(self, element_tree, parse_nodes, crs)

        # find and initialize the enter and leave locations
        r = element_tree

        self.name = r.findtext('name')
        if not self.name:
            raise SpecificationError, "<name> element missing in <split_location>"
        
        self.parse_cnt = 0
        self.trigger_cnt = 0
        self.trigger_nodes = {}    # list of parse nodes for 'enter' and 'leave'
        self.trigger_names = {}    # list of parse node names for 'enter' and 'leave'
        self.name_to_pn = {}       # mapping of value name to list of parse nodes [enter_pn, leave_pn]
        self.have_data = {}        # list of parse nodes that have data to be parsed
        self.enter_data = {}       # stack of results of parse_data() for each parse node
        self.store_names = {}      # map from name to store to operation to be applied
        self.content = {}

        att = get_attribute(r, "<tabular_value> %s" % self.name, "update", "no",
                            ['yes', 'no', 'auto'])
        if att in ('yes', 'auto'):
            self.update[self.name] = att

        for trg in ('enter', 'leave'):
            self.trigger_nodes[trg] = []
            self.trigger_names[trg] = []
            self.have_data[trg] = []
            
            trig_node = r.find(trg)
            if trig_node is None:
                raise SpecificationError, "<split_location> '%s': no <%s> element!" % (self.name, trg)

            for l in ('named_location', 'explicit_location', 'tabular_location'):
                 all_locs = trig_node.findall(l)
                 if all_locs != None:
                     for loc in all_locs:
                         pn = eval(l)(loc, parse_nodes, crs)

                         self.trigger_nodes[trg].append(pn)
                         for n in pn.get_value_names():
                             self.trigger_names[trg].append(n)
                             if not n in self.name_to_pn:
                                 self.name_to_pn[n] = []
                             self.name_to_pn[n].append(pn)
                         self.enter_data[pn] = []

            if len(self.trigger_nodes[trg]) == 0:
                raise SpecificationError, "<split_location> '%s': no sub-elements in <%s> element!" % (self.name, trg)

        store_node = r.find('store')
        if not store_node:
            raise SpecificationError, "<split_location> '%s': no <store> element!" % (self.name)
        for n in store_node.findall('name'):
            store_what = 'current'
            store_name = n.text            
            att = n.get('store')
            if att:
                if not att in ('current', 'enter', 'leave', 'max', 'min', 'diff', 'sum'):
                    raise SpecificationError, "<split_location> '%s': invalid content '%s' for atribute 'store' of <name> %s" \
                          % (self.name, att, store_name)
                store_what = att
            if store_what == 'enter':
                if not store_name in self.trigger_names['enter']:
                    raise SpecificationError, "<split_location> '%s': 'store' <name> %s not in <enter> list." \
                          % (self.name, store_name)
            if store_what == 'leave':
                if not store_name in self.trigger_names['leave']:
                    raise SpecificationError, "<split_location> '%s': 'store' <name> %s not in <leave> list." \
                          % (self.name, store_name)
            if store_what in ('max', 'min', 'diff', 'sum'):
                if not (store_name in self.trigger_names['enter'] and store_name in self.trigger_names['leave']):
                    raise SpecificationError, "<split_location> '%s': 'store' <name> %s not in <enter> and <leave> list." \
                          % (self.name, store_name)
            self.store_names[store_name] = store_what

        return

    def check_trigger(self, fname, idx):
        """Check if any of the parse nodes triggers on this line. If any of them does,
        we remember it and return its code back and call this parse node on the subsequent
        parse_data() call."""

        rc = 'Nothing'

        for t in ('enter', 'leave'):
            for pn in self.trigger_nodes[t]:
                action = pn.check_trigger(fname, idx)
                # 'new_run' is not handled for now
                if action == 'new_run':
                    raise SpecificationError, "run separation not supported for <split_location>"
                if action == 'parse':
                    self.have_data[t].append(pn)
                    rc = 'parse'
                    self.trigger_cnt += 1
        return rc

    def parse_data(self, fname, idx):
        """Get data from all parse nodes that triggered. Data from parse nodes that are defined
        in the 'enter' phase will be rememebered until triggers from the 'leave' phase deliver
        data and make it possible to relate the data from the two phases and then store it in
        the database."""
        rc = 'nothing'
        
        for pn in self.have_data['enter']:
            action = pn.parse_data(fname, idx)
            if action == 'store_value' or action == "store_set":
                # save data until it will actually be stored
                vc = pn.get_value_contents()
                if not pn in self.enter_data:
                    self.enter_data[pn] = []
                self.enter_data[pn].append(vc)
                if pb_debug:
                    print "#* storing 'enter' data:", vc
        self.have_data['enter'] = []

        leave_data = {}
        for pn in self.have_data['leave']:
            action = pn.parse_data(fname, idx)
            if action == 'store_value' or action == "store_set":
                # First gather all data as multiple of the parse nodes might want to store data,
                # i.e. if multiple named_locations are found in a single line.
                vc = pn.get_value_contents()
                leave_data[pn] = vc
                if pb_debug:
                    print "#* storing 'leave' data:", vc
        self.have_data['leave'] = []
                
        if len(leave_data) > 0:
            # Relate the 'leave' data to the 'enter' data and store the resulting data. Iterate
            # through the value names, and get the respective data.
            for vn, op in self.store_names.iteritems():
                try:
                    if op == 'enter':
                        pn = self.name_to_pn[vn][0]
                        d = self.enter_data[pn].pop()
                        result_c = d[vn]
                    elif op == 'leave':
                        pn = self.name_to_pn[vn][1]
                        d = leave_data[pn]
                        result_c = d[vn]
                    elif op == 'current':
                        # use either 'leave' or 'enter' content
                        pn = self.name_to_pn[vn][1]
                        if pn in leave_data:
                            d = leave_data[pn]
                        else:
                            if len(self.enter_data[pn]) > 0:
                                d = self.enter_data[pn].pop()
                            else:
                                # no data available!
                                print "#* PROBLEM: <split_location>: no current data available"
                        result_c = d[vn]
                    else:
                        # both 'leave' and 'enter' content need to exist
                        result_c = ''
                        try:
                            pn = self.name_to_pn[vn][0]
                            enter_d = self.enter_data[pn].pop()                            
                            pn = self.name_to_pn[vn][1]
                            leave_d = leave_data[pn]
                        except KeyError:
                            # Some data was not found in the input file, and thus the index does
                            # not return any data.
                            print "ERROR while parsing input file; probably incomplete line (line %d):" % (idx)
                            print get_dataline(fname, idx)
                            exit(1)
                            
                        enter_c = enter_d[vn]
                        leave_c = leave_d[vn]

                        if op == 'diff':
                            result_c = str(float(leave_c) - float(enter_c))
                        elif op == 'sum':
                            result_c = str(float(leave_c) + float(enter_c))
                        elif op == 'max':
                            result_c = str(max(float(leave_c), float(enter_c)))
                        elif op == 'min':
                            result_c = str(min(float(leave_c), float(enter_c)))
                except ValueError, msg:
                    print "ERROR while parsing input file; probably incomplete line (line %d):" % (idx)
                    print get_dataline(fname, idx)
                    print "PROBLEM:", msg
                    exit(1)
                except IndexError, msg:
                    print "ERROR while parsing input file; probably nesting mismatch (line %d):" % (idx)
                    print get_dataline(fname, idx)
                    print "PROBLEM:", msg
                    exit(1)
                # Now we have the tuple of 'value name' and 'value content' to be stored
                # as (vn, result_c).
                self.content[vn] = result_c                
                
            rc = 'store_set'
            self.parse_cnt += 1
            
        return rc

    def get_trigger_count(self):
        return self.trigger_cnt

    def get_parse_count(self):
        return self.parse_cnt

    def get_value_names(self):
        all_names = []
        for k in self.store_names.iterkeys():
            all_names.append(k)

        return all_names

    def get_value_contents(self, reset = True):
        d = self.content
        self.content = {}
        return d

    def new_run(self):
        rc = True

        self.have_data = {}
        for trg in ('enter', 'leave'):
            self.have_data[trg] = []
        self.parse_cnt = 0
        self.trigger_cnt = 0
        self.enter_data = {}
        for t in ('enter', 'leave'):
            for pn in self.trigger_nodes[t]:
                if not pn.new_run():
                    rc = False
        return rc


class named_location(input_parse):
    def __init__(self, element_tree, parse_nodes, crs):
        self.trigger_cnt = 1
        input_parse.__init__(self, element_tree, parse_nodes, crs)

        self.type = 'named'
        self.name = None
        self.content = None
        self.ws = whitespace
        self.match = []
        self.match_begin = []
        self.match_end = []
        self.regexp = []
        self.trigger = []
        self.skip = {}
        self.valid_vals = None
        self.is_numeric = False
        self.is_separator = False
        self.is_boolean = False
        self.do_accumulate = False
        self.do_abort = False
        self.accu = 0.0
        self.data_is_stored = False
        self.len = -1
        self.cntnt_follows = True
        
        r = element_tree

        self.name = r.findtext('name')
        if not self.name:
            raise SpecificationError, "<name> tag missing in <named_location>"

        # retrieve this value from the databae
        sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (self.name, ))
        nim = build_name_idx_map(crs)
        if crs.rowcount == 1:
            db_row = crs.fetchone()
            self.is_numeric = db_row[nim['is_numeric']]
            self.only_once  = db_row[nim['only_once']]
            self.datatype = db_row[nim['data_type']]
            # also store this info globally
            is_numeric[self.name] = self.is_numeric
            only_once[self.name] = self.only_once
            if db_row[nim['valid_values']] != None:
                self.valid_vals = db_row[nim['valid_values']]
        else:
            raise SpecificationError, "<named_location> for '%s': not a parameter or result value" %(self.name)

        self.retrigger = None
        att = get_attribute(r, "<named_location> %s" % self.name, "retrigger", "auto", ["auto", "yes", "no"])
        if att == 'yes':
            self.retrigger = True
        elif att == 'no':
            self.retrigger = False

        self.store_set = False    # this value triggers storing a set
        att = get_attribute(r, "<named_location> %s" % self.name, "store_set", "no", ["yes", "no"])
        if att == 'yes':
            self.store_set = True

        att = r.get("len")
        if att:
            try:
                self.len = int(att)
            except ValueError, error_msg:
                raise SpecificationError, "non-integer content '%s' for atribute 'len' in  <named_location> %s" \
                      % (att, self.name)                

        self.lines = -1
        att = r.get("lines")
        if att:
            try:
                self.lines = int(att)
            except ValueError, error_msg:
                raise SpecificationError, "non-integer content '%s' for atribute 'lines' in  <named_location> %s" \
                      % (att, self.name)
            if self.lines != 1 and db_row[nim['data_type']] not in ('string', 'text'):
                raise SpecificationError, "'lines' attribute only allowed for datatype 'text' or 'string' (<named_location> %s)" \
                      % (self.name)

        self.sticky = True
        att = get_attribute(r, "<named_location> %s" % self.name, "sticky", "yes", ["yes", "no"])
        if att == "no":
            self.sticky = False

        att = get_attribute(r, "<named_location> %s" % self.name, "update", "no",
                            ['yes', 'no', 'auto'])
        if att in ('yes', 'auto'):
            self.update[self.name] = att

        self.counter = -1    # '-1' means assign-mode, '>= 0' is count mode
        mode_att = get_attribute(r, "<named_location> %s" % self.name, "mode", "assign",
                                 ["count", "assign", "set", "boolean", "accumulate", "abort"])
        if mode_att in ( "count", "boolean" ):
            self.counter = 0
            self.len = 0
            # check if the type of the assigned variable is valid
            if not self.only_once:
                raise SpecificationError, "<named_location> '%s': '%s' mode requires 'occurrence=once' attribute" \
                      % (self.name, mode_att)
            if mode_att == 'count':
                if not self.is_numeric:
                    raise SpecificationError, "<named_location> '%s': '%s' mode requires numeric variable" \
                          % (self.name, mode_att)
            if mode_att == 'boolean':
                # 'boolean' mode is very similar to the 'count' mode: if count will be > 0,
                # it returns 'True'.
                self.is_boolean = True
                # 't' and 'f' are the SQL representations of boolean states
                self.content = 'f'
                self.data_is_stored = True
        elif mode_att == "set":
            # This named variable is part of a set, and this set will be stored if
            # this content for this variable is found.
            self.store_set = True
            # Only in here for backward compatibility. Usage depreciated.
            print "#* WARNING: attribute content 'set' is depreciated. Use attribute 'store_set' instead."
        elif mode_att == "accumulate":
            self.do_accumulate = True
            if not self.is_numeric:
                raise SpecificationError, "<named_location> '%s': '%s' mode requires numeric variable" \
                      % (self.name, mode_att)
        elif mode_att == "abort":
            self.do_abort = True

        
        att = get_attribute(r, "<named_location> %s" % self.name, "content", "follows",
                            ['leads', 'follows'])
        if att == "leads":
            self.cntnt_follows = False

        self.dflt_match_type = get_attribute(r, "<named_location> %s" % self.name, "match", "exact",
                                             ['exact', 'fuzzy'])
        if self.dflt_match_type == "fuzzy":
            print "#* WARNING: attribute 'match=fuzzy' not yet implemented for <named_location>"

        for t in r.findall('trigger'):
            # XXX why set the len to 0 for a trigger?
            # self.len = 0
            new_trigger = {}

            for n_name in ['skip', 'match', 'regexp']:
                n = t.findtext(n_name)
                if n:
                    new_trigger[n_name] = n
            if new_trigger.has_key('skip'):
                new_trigger['skip'] = int(new_trigger['skip'])
            else:
                new_trigger['skip'] = 0
            if not (new_trigger.has_key('match') or new_trigger.has_key('regexp')):
                raise SpecificationError, "neither <match> nor <regexp> tag found in <trigger>"
            if new_trigger.has_key('regexp'):
                try:
                    new_trigger['regexp'] = re.compile(new_trigger['regexp'])
                except sre_constants.error:
                    raise SpecificationError, "named_location '%s': invalid trigger regexp '%s'" % (self.name, new_trigger['regexp'])

            self.trigger.append(new_trigger)

        f = r.find('filter')
        if f is not None:
            f_flags = 0
            f_att = f.get('case')
            if f_att:
                if not f_att in ("ignore", "respect"):
                    raise SpecificationError, "Invalid content '%s' for filter attribute of <named_location> '%s'" \
                          % (f_att, self.name)
                if f_att == 'ignore':
                    f_flags = re.IGNORECASE            
            self.filter = re.compile(f.text, f_flags)

        self.mappings = {}
        self.map_regexp = []
        for m in r.findall('map'):
            c_in  = m.find('content_in')
            c_out = m.find('content_out')
            if c_in is None or c_out is None or len(c_in.text) == 0 or len(c_out.text) == 0:
                raise SpecificationError, " <named_location> '%s': <map> needs <content_in> and <content_out> elements."\
                      % self.name
            if not self.valid_vals is None:
                if not c_out.text in self.valid_vals:
                    raise SpecificationError, " <named_location> '%s': <content_out> '%s' is not <valid> content."\
                          % (self.name, c_out.text)
                self.valid_vals.append(c_in.text)
            att = get_attribute(c_in, "<derived_parameter> %s" % self.name, "match", "literal",
                                ['literal', 'regexp'])
            if att == "regexp":
                regexp = re.compile(c_in.text)
                self.map_regexp.append(regexp)
                self.mappings[regexp] = c_out.text
            else:
                self.mappings[c_in.text] = c_out.text

        self.terminator = { None : None }
        for m in r.findall('match'):
            m_att = m.get('marker')
            if m_att:
                if m_att in ("begin"):
                    self.match_begin.append(m.text)
                    skip = m.get('skip')
                    if skip:
                        self.skip[m.text] = int(skip)
                elif m_att in ("end"):
                    self.match_end.append(m.text)
                else:
                    raise SpecificationError, "Invalid content '%s' for marker attribute of <match> '%s' in <named_location> '%s'" \
                          % (m_att, m.text, self.name)
            else:
                self.match.append(m.text)
                self.terminator[m.text] = m.get("terminator")
            
        for m in r.findall('regexp'):
            # any exception to catch?
            try:
                regexp = re.compile(m.text)
            except sre_constants.error:
                raise SpecificationError, "named_location '%s': invalid regexp '%s'" % (self.name, m.text)
            self.regexp.append(regexp)
            self.terminator[regexp] = None

        ws = r.findtext('ws')
        if ws:
            self.ws = ws + self.ws
        att = r.get('is_separator')
        if att and not cmp(lower(att), 'yes'):
            self.is_separator = True

        if len(self.match) + len(self.match_begin) + len(self.regexp) + len(self.trigger) == 0:
            if self.valid_vals is None:
                raise SpecificationError, "No <match>, <regexp> or <trigger> provided for <named_location> '%s'." \
                      % self.name
            else:
                # match the content as keyword (or its mapping-from)
                self.len = 0
                for v in self.valid_vals:
                    self.match.append(v)
                for k in self.mappings.iterkeys():
                    if isinstance(k, str): 
                        self.match.append(k)
                    else:
                        self.regexp.append(k)

        # scale the content before storing it (useful to adapt to given units)
        self.scale = None
        scale_att = r.get("scale")
        if scale_att is not None:
            if not self.is_numeric:
                raise SpecificationError, "named_location '%s': scale attribute only valid for numeric values." % (v_name)
            try:
                if self.datatype[:7] == 'integer':
                    scale_fact = int(scale_att)
                else:
                    scale_fact = float(scale_att)
            except ValueError:
                raise SpecificationError, "named_location '%s': invalid scale attribute '%s' (NaN)." % (v_name, scale_att)
            self.scale = scale_fact

        if self.retrigger is None:
            self.retrigger = not (self.only_once and self.counter < 0 and not self.do_accumulate)

        return

    def check_trigger(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        if self.parse_cnt > 0 and not self.retrigger:
            return "remove"

        self.data_match = None
        self.data_match_begin = None
        self.data_re = None
        rval = "nothing"

        for t in self.trigger:
            try:
                if t.has_key('match'):
                    if get_dataline(fname, idx - t['skip']).find(t['match']) != -1:
                        rval = "parse"
                elif t['regexp'].search(get_dataline(fname, idx - t['skip'])):
                    rval = "parse"
            except IndexError:
                continue
            if rval == "parse":
                if pb_debug:
                    print "#* checking <named_location>: trigger matched (skip %d)" % (t['skip'])
                break

        # If a trigger is supplied, then we don't use the other matches - it's the trigger's
        # task to determine if a line matches. The match and/or regexp that may be supplied, too,
        # are then used to find the data within this line!
        if len(self.trigger) == 0 or rval == 'parse':
            for m in self.match:
                if get_dataline(fname, idx).find(m) != -1:
                    if pb_debug:
                        print "#* checking <named_location>: found '%s'" % (m, )
                    self.data_match = m
                    rval = "parse"
                    break

            for m in self.match_begin:
                if get_dataline(fname, idx).find(m) != -1:
                    if pb_debug:
                        print "#* checking <named_location>: found '%s'" % m
                    self.data_match_begin = m;
                    rval = "parse"
                    break

            for r in self.regexp:
                if r.search(get_dataline(fname, idx)):
                    self.data_re = r
                    rval = "parse"
                    break

        if rval != "parse" and idx == line_cnt[fname] and (self.counter >= 0 or self.do_accumulate):
            # count, boolean and accumulate modes needs to write out the data
            # at the end of the file
            rval = "parse"
        
        if rval == "parse":
            self.trigger_cnt += 1
            if self.is_separator:
                rval = "new_run"
            if self.do_abort:
                rval = "abort"

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['check_trigger'].append(t0)

        return rval

    def parse_data(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        match_str = ""
        partial_line = [ "" ]
        line_idx = 0
        term_idx = None
        if self.cntnt_follows:
            line_idx = 1

        if self.lines >= 0:               
            # read some lines of raw text
            if self.lines > 0:
                if self.data_match:
                    # skip the match
                    self.content = get_dataline(fname, idx).split(self.data_match, 2)[1]
                else:
                    self.content = get_dataline(fname, idx)
                for l in range(idx+1, idx+self.lines):
                    self.content += get_dataline(fname, l)
            else:
                self.content = ""
                i = idx
                try:
                    while len(strip(get_dataline(fname, i))) > 0:
                        if self.data_match and i == idx:
                            # skip the match which is located in the first line
                            self.content = get_dataline(fname, i).split(self.data_match, 2)[1]
                        else:
                            self.content += get_dataline(fname, i)
                        i += 1
                except IndexError:
                    pass

            if pb_profiling:
                t0 = time.clock() - t0
                self.prof_data['parse_data'].append(t0)

            self.parse_cnt += 1
            if self.store_set:
                return "store_set"
            else:
                return "store_value"

        if self.data_match_begin:
            # read until a string in match_end is set
            #self.content = lines[idx].split(self.data_match_begin, 2)[1]
            if not self.skip.has_key(self.data_match_begin) or self.skip[self.data_match_begin] == 0:
                self.content = (get_dataline(fname, idx).split(self.data_match_begin, 2)[1]).strip()
                if self.content:
                    self.content += "\n"
                i = idx + 1
            else:
                self.content = ""
                i = idx + self.skip[self.data_match_begin]

            try:
                run = True
                while run:
                    for m in self.match_end:                        
                        p = get_dataline(fname, i).find(m)
                        if p >= 0:
                            self.content += get_dataline(fname, i)[0:p].strip()
                            run = False
                            break
                    else:
                        self.content += get_dataline(fname, i)
                    i += 1
            except IndexError:
                # This means we hit EOF - no content should be saved.
                self.content = ""

            if pb_profiling:
                t0 = time.clock() - t0
                self.prof_data['parse_data'].append(t0)

            self.content = clean_string(self.content)
            self.parse_cnt += 1
            if self.store_set:
                return "store_set"
            else:
                return "store_value"

        if self.data_match:
            if pb_debug:
                print "#* parsing <named_location> '%s'" % (self.data_match, )
            if self.counter >= 0:
                # count this occurrence
                self.counter += get_dataline(fname, idx).count(self.data_match)
                match_str = str(self.counter)
            elif self.valid_vals and self.valid_vals.count(self.data_match) > 0:
                # found one of the valid values itself
                match_str = self.data_match
            elif self.valid_vals and self.mappings.has_key(self.data_match) and \
                     self.valid_vals.count(self.mappings[self.data_match]) > 0:
                # the mapped string is a valid value
                match_str = self.mappings[self.data_match]
            else:
                # conventional "keyword matching", looking for the content either in front
                # of the keyword or behind.
                partial_line = split(get_dataline(fname, idx), self.data_match, 1)
                if len(partial_line) > 1 and len(partial_line[line_idx]) > 0:
                    # remember everything in front or behind
                    match_str = strip(partial_line[line_idx])
                else:                    
                    # no content found!
                    self.data_match = None
                    if pb_profiling:
                        t0 = time.clock() - t0
                        self.prof_data['parse_data'].append(t0)
                        return "nothing"
            term_idx = self.data_match
            self.data_match = None
        elif self.data_re:
            # Use a regular expression to find matching data. We can also be looking for one 
            # of the valid values" being mapped to this regexp!
            if self.counter >= 0:
                # Count this occurrence. XXX This construct is a little bit weak with
                # respect to possible groups of the regexp!
                self.counter += len(self.data_re.findall(get_dataline(fname, idx)))
                match_str = str(self.counter)
            else:
                partial_line = self.data_re.split(get_dataline(fname, idx))
                if len(partial_line) > 3:
                    # This regexp made use of two or more groups. The last element in this list
                    # is the line break which we omitt; the other elements are joined to form the
                    # match string.
                    match_str = ''.join(partial_line[0:-1])
                elif len(partial_line) > 1 and len(partial_line[line_idx]) > 0:
                    # Either a single group to remember, or we remember everything in front or behind
                    # of a keyword.
                    match_str = strip(partial_line[line_idx])
                # Check if there's a mapping for the matched string.
                if self.valid_vals and self.mappings.has_key(self.data_re) and \
                       self.valid_vals.count(self.mappings[self.data_re]) > 0:
                    # the mapped string is a valid value
                    match_str = self.mappings[self.data_re]
                else:
                    # no content found!
                    self.data_re = None
                    if pb_profiling:
                        t0 = time.clock() - t0
                        self.prof_data['parse_data'].append(t0)
                        return "nothing"

            term_idx = self.data_re
            self.data_re = None
        elif len(self.trigger) > 0:
            # No match, no regexp: a trigger has fired, and we take the current line as input
            match_str = strip(get_dataline(fname, idx))
            term_idx = None
            
        if self.cntnt_follows:
            match_idx = 0
        else:
            match_idx = -1

        if self.len < 0:
            # auto-mode
            if self.terminator[term_idx] is None:
                # check all defined "whitespace" characters one by one if they
                # split up the string. The first ws character that does is used.
                for ws_idx in range(len(self.ws)-1, -1, -1):
                    ws_tokens = match_str.split(self.ws[ws_idx])
                    if len(ws_tokens) > 1 and len(ws_tokens[match_idx]) > 0:
                        break
                self.content = strip(ws_tokens[match_idx])
            else:
                self.content = strip(split(match_str, self.terminator[term_idx], 1)[match_idx])
        elif self.len > 0:
            # take a string of specified length
            self.content = strip(match_str[:self.len])
        else:
            # take the whole line - but not for 'boolean' parsing which does not
            # actually need any content.
            if not self.is_boolean:
                self.content = strip(match_str)

        self.content = clean_string(self.content)
        if len(self.content) == 0 and (self.counter < 0 and idx + 1 <= line_cnt[fname]):
            # No content found => exit. Shouldn't happen often, but can be the case
            # for invalid number formats etc.. Exception is for counter and boolean
            # variables which need to get flushed at the end of the input file.
            self.data_match = None
            self.content = None
            if pb_profiling:
                t0 = time.clock() - t0
                self.prof_data['parse_data'].append(t0)
            return "nothing"

        if self.filter is not None:
            self.content = ''.join(self.filter.split(self.content))

        if self.mappings.has_key(self.content):
            self.content = self.mappings[self.content]
        else:
            for r in self.map_regexp:
                if r.search(self.content):
                    self.content = self.mappings[r]

        if self.is_numeric:
            # "smart-convert" string into a number
            self.content = str_to_number(self.content)
            if self.scale:
                # datatype can be "integer(4)" or "integer(8)", so just compare first 7 characters.
                if self.datatype[:7] == 'integer':
                    v_number = int(self.content)
                    self.content = str(int(self.scale*v_number))
                else:
                    v_number = float(self.content)
                    self.content = str(self.scale*v_number)
                
        if self.only_once:
            if self.counter < 0 and not self.do_accumulate:
                # assign mode
                if len(self.content) == 0:
                    # Probably, this was not a number...
                    rval = "nothing"
                else:
                    if not self.data_is_stored:
                        # Is it an error if data is already stored?
                        self.data_is_stored = True
                        self.parse_cnt += 1
                    rval = "store_value"
            else:
                # count, accumulate or boolean mode
                self.parse_cnt += 1
                if idx == line_cnt[fname]:
                    # Content must not be stored in the database until the end of the file.
                    if self.is_boolean:
                        if self.counter > 0:
                            # 't' and 'f' are the SQL representations of boolean states
                            self.content = 't'
                    elif self.do_accumulate:
                        # Take care of possible content in the last line of the file!
                        if term_idx is not None:
                            self.accu += float(self.content)
                        self.content = str(self.accu)
                    else:
                        self.content = str(self.counter)
                    self.data_is_stored = True
                    rval = "store_value"
                else:
                    if self.do_accumulate and len(self.content) > 0:
                        self.accu += float(self.content)
                    rval = "nothing"
            if pb_profiling:
                t0 = time.clock() - t0
                self.prof_data['parse_data'].append(t0)

            if pb_debug:
                print "   content for '%s': '%s'" % (self.name, self.content)
                
            return rval
        else:
            self.parse_cnt += 1            

        if self.is_numeric and len(self.content) == 0:
            # Probably, this was not a number...forget the data!
            self.content = None
            rval = "nothing"
        else:
            if self.store_set:
                rval = "store_set"
            else:
                # don't store the set yet, but remember the data
                rval = "nothing"
            if pb_debug:
                print "   content for '%s': '%s'" % (self.name, self.content)
            
        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['parse_data'].append(t0)

        return rval

    def get_value_names(self):
        l = [ self.name ]
        return l

    def get_value_contents(self, reset = True):
        d = None
        if self.content is not None:
            d = { self.name:self.content }
        if self.counter >= 0:
            # this is only relevant for the special case "new_run triggered inside a file"
            self.data_is_stored = True
        if not self.sticky:
            self.content = None
        return d

    def new_run(self):
        self.parse_cnt = 0
        self.trigger_cnt = 0
        self.accu = 0.0
        if self.is_boolean:
            self.content = 'f'
        else:
            self.content = None
        if self.counter >= 0:
            if not self.data_is_stored:
                self.content = str(self.counter)
                return False        
            self.counter = 0
        self.data_is_stored = False
        return True


class filename_location(input_parse):
    def __init__(self, element_tree, parse_nodes, crs):
        input_parse.__init__(self, element_tree, parse_nodes, crs)

        self.type = 'filename'
        self.name = None
        self.content = None
        self.ws = whitespace
        self.match = []
        self.regexp = []
        self.valid_vals = None
        self.is_boolean = False

        r = element_tree

        self.dflt_match_type = "exact"
        match_att = r.get("match")
        if match_att:
            if not match_att in ("exact", "fuzzy"):
                raise SpecificationError, "Invalid content '%s' for match attribute of <filename_location> '%s'" \
                      % (match_att, self.name)
            self.dflt_match_type = match_att
        
        self.name = r.findtext('name')
        if not self.name:
            raise SpecificationError, "<name> tag missing in <filename_location> '%s'" % self.name

        # retrieve this value from the databae
        sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (self.name, ))
        nim = build_name_idx_map(crs)
        if crs.rowcount == 1:
            db_row = crs.fetchone()
            self.is_numeric = db_row[nim['is_numeric']]
            self.only_once  = db_row[nim['only_once']]
            # also store this info globally
            is_numeric[self.name] = self.is_numeric
            only_once[self.name] = self.only_once
            if db_row[nim['valid_values']] != None:
                self.valid_vals = db_row[nim['valid_values']]
        else:
            raise SpecificationError, "<filename_location>: unknown parameter or result '%s'" % self.name

        self.len = -1
        len_att = r.get("len")
        if len_att:
            self.len = int(len_att)

        self.counter = -1    # '-1' means assign-mode, '>= 0' is count mode
        mode_att = r.get("mode")
        if mode_att:
            if not mode_att in ("assign", "boolean"):
                raise SpecificationError, "<named_location> '%s': invalid content '%s' of 'mode' attribute" \
                      % (self.name, mode_att)
            if mode_att == "boolean":
                self.is_boolean = True
                self.len = 0
                # check if the type of the assigned variable is valid
                if not self.only_once:
                    raise SpecificationError, "<named_location> '%s': '%s' mode requires 'occurrence=once' attribute" \
                          % (self.name, mode_att)
                # 't' and 'f' are the SQL representations of boolean states; here, we set the default:
                # if nothing is found, the content is 'false'
                self.content = 'f'

        f = r.find('filter')
        if f is not None:
            f_flags = 0
            f_att = f.get('case')
            if f_att:
                if not f_att in ("ignore", "respect"):
                    raise SpecificationError, "Invalid content '%s' for filter attribute of <filename_location> '%s'" \
                          % (f_att, self.name)
                if f_att == 'ignore':
                    f_flags = re.IGNORECASE            
            self.filter = re.compile(f.text, f_flags)

        self.match_type = {}
        self.terminator = {}
        for m in r.findall('match'):
            self.match.append(m.text)
            self.terminator[m.text] = m.get("terminator")
            self.match_type[m.text] = self.dflt_match_type
            match_att = m.get("match")
            if match_att:
                if not match_att in ("exact", "fuzzy"):
                    raise SpecificationError, "Invalid content '%s' for <match> '%s' of <filename_location> '%s'" \
                          % (match_att, m.text, self.name)
                self.match_type[m.text] = match_att
          
        for m in r.findall('regexp'):
            new_re = re.compile(m.text)
            self.regexp.append(new_re)
            self.terminator[new_re] = None
        ws = r.findtext('ws')
        if ws:
            self.ws = self.ws + ws

        self.mappings = {}
        for m in r.findall('map'):
            c_in  = m.findtext('content_in')
            c_out = m.findtext('content_out')
            if c_in is None or c_out is None or len(c_in) == 0 or len(c_out) == 0:
                raise SpecificationError, " <filename_location> '%s': <map> needs <content_in> and <content_out> elements." % self.name
            if not self.valid_vals is None:
                if not c_out in self.valid_vals:
                    raise SpecificationError, " <filename_location> '%s': <content_out> '%s' is not <valid> content." % (self.name, c_out)
                self.valid_vals.append(c_in)
            self.mappings[c_in] = c_out            

        if len(self.match) + len(self.regexp) == 0:
            # We do not need a <match> if the value was defined with a selection of
            # <valid> tags. In this case, it is sufficient if we find one of these within
            # the filename.
            if self.valid_vals is None:
                raise SpecificationError, "No <match> or <regexp> provided for <filename_location> '%s'." \
                      % self.name
            else:
                self.len = 0
                for v in self.valid_vals:
                    self.match.append(v)
                    self.match_type[v] = "exact"
                # also add the content that will be mapped onto one of the valid values
                for k in self.mappings.iterkeys():
                    self.match.append(k)
                    self.match_type[k] = "exact"

        match_tmp = []
        match_tmp.extend(self.match)
        for m in match_tmp:
            if self.match_type[m] == "fuzzy":
                # 'fuzzy' means: create (two) variations of the keyword which also do match
                m_alt = m.lower()
                self.match.append(m_alt)
                if self.terminator.has_key(m):
                    self.terminator[m_alt] = self.terminator[m]
                self.match_type[m_alt] = "fuzzy"

                m_alt = m.replace('_','').lower()
                if self.terminator.has_key(m):
                    self.terminator[m_alt] = self.terminator[m]
                self.match.append(m_alt)
                self.match_type[m_alt] = "fuzzy"
                
        return
    
    def check_trigger(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        self.data_match = None
        self.data_re = None
        rval = "nothing"

        for m in self.match:
            line = get_dataline(fname, idx)
            if self.match_type[m] == "fuzzy":
                line = get_dataline(fname, idx).lower()
            if find(get_dataline(fname, idx), m) != -1:
                if pb_debug:
                    print "#* checking <filename_location>: found '%s'" % (m, )
                self.data_match = m
                rval = "parse"
        for r in self.regexp:
            if r.search(get_dataline(fname, idx)):
                if pb_debug:
                    print "#* checking <filename_location>: regexp '%s' matched" % (self.name, )
                self.data_re = r
                rval = "parse"
        if self.is_boolean:
            # for boolean, either 't' (found) or 'f' (not found) is always returned!
            rval = "parse"
        if rval == "parse":
            self.trigger_cnt += 1

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['check_trigger'].append(t0)
            
        return rval

    def parse_data(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        match_str = ""
        partial_line = [ "" ]
        if self.data_match:
            if pb_debug:
                print "#* parsing <filename_location> '%s'" % self.data_match
                print self.valid_vals
            if self.valid_vals and self.valid_vals.count(self.data_match) > 0:
                # found the value itself within the filename
                match_str = self.data_match
            else:
                # conventional "keyword matching"
                partial_line = split(get_dataline(fname, idx), self.data_match, 1)
                if len(partial_line) > 1:
                    if len(partial_line[1]) == 0:
                        # no data found
                        if pb_profiling:
                            t0 = time.clock() - t0
                            self.prof_data['parse_data'].append(t0)
                        return "nothing"
                    # 'self.data_match' is actually contained (it should!)
                    if self.len < 0:
                        # 'auto-mode': take the first element.
                        match_str = (split(partial_line[1], None, 1))[0]
                    else:
                        match_str = partial_line[1]
                else:
                    # no data found
                    if pb_profiling:
                        t0 = time.clock() - t0
                        self.prof_data['parse_data'].append(t0)
                    return "nothing"
                term_idx = self.data_match
                self.data_match = None
        elif self.data_re:
            partial_line = self.data_re.split(get_dataline(fname, idx), 1)
            if pb_debug:
                print "#* parsing <filename_location>: partial_line", partial_line
            for p in partial_line:                
                if p is not None and len(p) > 0:
                    match_str = p
                    break
            term_idx = self.data_re
            self.data_re = None
        elif self.is_boolean:
            # nothing found, return "false"
            self.content = 'f'
            self.parse_cnt += 1
            return "store_value"

        if self.len < 0:
            if self.terminator[term_idx] is None:
                # auto-mode
                partial_line = split(match_str, self.ws, 1)
            else:
                partial_line = split(match_str, self.terminator[term_idx], 1)
        elif self.len > 0:
            # take a string of specified length
            partial_line[0] = match_str[:self.len]
        else:
            # take the whole line
            partial_line[0] = match_str
            
        self.content = strip(partial_line[0])
        self.content = clean_string(self.content)

        if self.filter is not None:
            self.content = ''.join(self.filter.split(self.content))

        if self.mappings.has_key(self.content):
            self.content = self.mappings[self.content]
        if self.is_boolean:
            self.content = 't'
        if self.is_numeric:
            # "smart-convert" string into a number
            self.content = str_to_number(self.content)
        if pb_debug:
            print "   content for '%s': '%s'" % (self.name, self.content)

        # Is it an error if data is already stored?
        self.parse_cnt += 1
        rval = "store_value"

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['parse_data'].append(t0)
        return rval 

    def get_value_names(self):
        l = [ self.name ]
        return l

    def get_value_contents(self, reset = True):
        d = None
        if self.content is not None:
            d = { self.name:self.content }
        return d

    def new_run(self):
        self.parse_cnt = 0
        self.trigger_cnt = 0
        return True


class explct_location(input_parse):
    def __init__(self, element_tree, parse_nodes, crs):
        input_parse.__init__(self, element_tree, parse_nodes, crs)

        self.type = 'explicit'
        self.name = None
        self.content = None
        self.ws = whitespace
        self.pos = None
        self.rep = None
        self.line_nbr = 0            # current line nbr (in file or separator section)
        self.trigger_row_nbr = -1    # user-specified row number that triggers this value
        self.trigger_skip_cnt = 0    # user-specified number of rows to skip before triggering
        self.trigger = -1            # current count-down value to trigger
        self.match = []
        self.regexp = []
        self.is_separator = False
        self.data_is_stored = False
        self.parse_cnt = 0

        r = element_tree
        n = r.findtext('name')
        if n:
            self.name = n
        else:
            raise SpecificationError, "<name> tag missing in <explicit_location>"
        # retrieve this value from the databae
        sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (self.name, ))
        nim = build_name_idx_map(crs)
        if crs.rowcount == 1:
            db_row = crs.fetchone()
            self.is_numeric = db_row[nim['is_numeric']]
            self.only_once  = db_row[nim['only_once']]
            # also store this info globally
            is_numeric[self.name] = self.is_numeric
            only_once[self.name] = self.only_once
        else:
            raise SpecificationError, "<explicit_location>: unknown value '%s'" % self.name
            
        att = get_attribute(r, "<explct_location> %s" % self.name, "update", "no",
                            ['yes', 'no', 'auto'])
        if att in ('yes', 'auto'):
            self.update[self.name] = att

        for m in r.findall('match'):
            self.match.append(m.text)
        for m in r.findall('regexp'):
            self.regexp.append(re.compile(m.text))
            # any exception to catch?

        f = r.find('filter')
        if f is not None:
            f_flags = 0
            f_att = f.get('case')
            if f_att:
                if not f_att in ("ignore", "respect"):
                    raise SpecificationError, "Invalid content '%s' for filter attribute of <explicit_location> '%s'" \
                          % (f_att, self.name)
                if f_att == 'ignore':
                    f_flags = re.IGNORECASE            
            self.filter = re.compile(f.text, f_flags)

        self.mappings = {}
        for m in r.findall('map'):
            c_in  = m.findtext('content_in')
            c_out = m.findtext('content_out')
            if c_in is None or c_out is None or len(c_in) == 0 or len(c_out) == 0:
                raise SpecificationError, " <explct_location> '%s': <map> needs <content_in> and <content_out> elements." % self.name
            self.mappings[c_in] = c_out            

        n = r.findtext('row')
        if n:
            self.trigger_row_nbr = n
        n = r.findtext('skip')
        if n:
            self.trigger_skip_cnt = n
        n = r.findtext('pos')
        if n:
            self.pos = n
        n = r.findtext('rep')
        if n:
            self.rep = n
        ws = r.findtext('ws')
        if ws:
            self.ws = self.ws + ws
        att = r.get('is_separator')
        if att and not cmp(lower(att), 'yes'):
            self.is_separator = True

        if not self.name:
            raise SpecificationError, 'No value name provided for <named_location>.'
        if len(self.match) + len(self.regexp) == 0:
            raise SpecificationError, 'No <match> and no <regexp> provided for <named_location>.'
        
        return
    
    def check_trigger(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        rval = "nothing"
        
        self.line_nbr = self.line_nbr + 1
        if self.trigger > 0:
            self.trigger = self.trigger - 1
        else:
            if self.line_nbr == self.trigger_row_nbr:
                self.trigger = self.trigger_skip_cnt
            for m in self.match:
                if find(get_dataline(fname, idx), m) != -1:
                    self.trigger = self.trigger_skip_cnt
            for r in self.regexp:
                if (r.search(get_dataline(fname, idx))):
                    self.trigger = self.trigger_skip_cnt

        if self.trigger == 0:
            self.trigger = -1
            self.trigger_cnt += 1
            if self.is_separator:
                rval = "new_run"
            else:
                rval = "parse"

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['check_trigger'].append(t0)
        
        return "nothing"

    def parse_data(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()
        rval = "nothing"
        
        self.content = split(get_dataline(fname, idx), self.ws)[self.pos]
        # value specification by keyword is not yet implemented.
        self.content = clean_string(self.content)
        if self.mappings.has_key(self.content):
            self.content = self.mappings[self.content]
        if self.is_numeric:
            self.content = str_to_number(self.content)
        if self.only_once:
            if not self.data_is_stored:
                # Is it an error if data is already stored?
                self.data_is_stored = True
                self.parse_cnt += 1
                rval = "store_value"

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['parse_data'].append(t0)
        return rval

    def get_value_names(self):
        l = [ self.name ]
        return l

    def get_value_contents(self, reset = True):
        d = None
        if self.content is not None:
            d = { self.name:self.content }
        return d

    def new_run(self):
        self.parse_cnt = 0
        self.trigger_cnt = 0
        self.data_is_stored = False
        self.line_nbr = 0
        self.trigger = -1
        return True


class tabular_location(input_parse):
    def __init__(self, element_tree, parse_nodes, crs):
        input_parse.__init__(self, element_tree, parse_nodes, crs)

        self.type = 'tabular'
        self.names = []
        self.contents = None
        self.vpos = {}
        self.vmatch = {}
        self.mappings = {}
        self.map_regexp = {}
        self.is_numeric = {}
        self.datatype = {}
        self.filters = {}
        self.ws = None
        self.rep = None
        self.line_nbr = 0            # current line nbr (in file or separator section)
        self.trigger_row_nbr = -1    # user-specified row number that triggers this value
        self.trigger_skip_cnt = 0    # user-specified number of rows to skip before triggering
        self.trigger = -1            # current count-down value to trigger
        self.inside_table = False
        self.match = []
        self.regexp = []
        self.scale = {}
        self.is_separator = False
        self.nbr_columns = 0
        self.nbr_rows = -1
        self.rows_parsed = 0
        self.only_once = False
        self.triggered_new_run = False
        
        e = element_tree

        # gather all the values which will be found in the table
        for t in e.findall('tabular_value'):
            v_name = t.findtext('name')
            if not v_name:
                raise SpecificationError, 'No value <name> provided for <tabular_value>.'
            if self.names.count(v_name) > 0:
                raise SpecificationError, "value name '%s' was defined more than once for <tabular_value>." % vn
            self.names.append(v_name)

            att = get_attribute(t, "<tabular_value> %s" % v_name, "update", "no",
                                ['yes', 'no', 'auto'])
            if att in ('yes', 'auto'):
                self.update[v_name] = att

            self.mappings[v_name] = {}
            self.map_regexp[v_name] = []
            for m in t.findall('map'):
                c_in  = m.find('content_in')
                c_out = m.find('content_out')
                if c_in is None or c_out is None or len(c_in.text) == 0 or len(c_out.text) == 0:
                    raise SpecificationError, " <tabular_value> '%s': <map> needs <content_in> and <content_out> elements." % v_name
                att = c_in.get("match")
                if att is not None and att == "regexp":
                    regexp = re.compile(c_in.text)
                    self.map_regexp[v_name].append(regexp)
                    self.mappings[v_name][regexp] = c_out.text
                else:
                    self.mappings[v_name][c_in.text] = c_out.text

            # retrieve this value from the databae
            sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (v_name, ))
            nim = build_name_idx_map(crs)
            if crs.rowcount == 1:
                db_row = crs.fetchone()
                self.is_numeric[v_name] = db_row[nim['is_numeric']]
                self.datatype[v_name] = db_row[nim['data_type']]
                is_numeric[v_name] = self.is_numeric[v_name]
                only_once[v_name] = db_row[nim['only_once']]
                if db_row[nim['only_once']] and pb_verbose:
                    print "#* WARNING: tabular value '%s' has occurrence 'once'" % v_name
                    self.only_once = True
            else:
                raise SpecificationError, "Invalid name '%s' in <tabular_value> of <tabular_location> '%s'" \
                      % (v_name, self.name)

            # scale the content before storing it (useful to adapt to given units)
            self.scale[v_name] = None
            scale_att = t.get("scale")
            if scale_att is not None:
                if not self.is_numeric[v_name]:
                    raise SpecificationError, "tabular_value '%s': scale attribute only valid for numeric values)." % (v_name)
                try:
                    if self.datatype[v_name] == 'integer':
                        scale_fact = int(scale_att)
                    else:
                        scale_fact = float(scale_att)
                except ValueError:
                    raise SpecificationError, "tabular_value '%s': invalid scale attribute '%s' (NaN)." % (v_name, scale_att)
                self.scale[v_name] = scale_fact

            m = t.findtext('match')
            if m:
                self.vmatch[v_name] = m

            if not self.vmatch.has_key(v_name):
                n = t.findtext('pos')
                if not n:
                    # If this is the first tabular_value, look for it in the first column. Otherwise,
                    # this means "look in next column (to the right) after the previous value" (to be refined)
                    if len(self.names) == 0:
                        n = 0
                    else:
                        n = -1
                try:
                    self.vpos[v_name] = int(n)
                except:
                    raise SpecificationError, "tabular_value '%s': <pos> content %s invalid (integer required)" % (v_name, n)            

            self.filters[v_name] = None
            f = t.find('filter')
            if f is not None:
                f_flags = 0
                f_att = f.get('case')
                if f_att:
                    if not f_att in ("ignore", "respect"):
                        raise SpecificationError, "Invalid content '%s' for filter attribute of <tabular_value> '%s'" \
                              % (f_att, v_name)
                    if f_att == 'ignore':
                        f_flags = re.IGNORECASE
                self.filters[v_name] = re.compile(f.text, f_flags)

        if len(self.names) == 0:
            raise SpecificationError, 'No <tabular_value>s provided for <tabular_location>.'

        # trigger conditions
        for m in e.findall('match'):
            if m.text is None:                
                self.match.append("")  # empty match => matches everything
            else:
                self.match.append(m.text)
        for m in e.findall('regexp'):
            self.regexp.append(re.compile(m.text))
            # any exception to catch?
        rows = e.findall('row')
        if len(rows) > 1:
            raise SpecificationError, 'Only one <row> element allowed for <tabular_value>.'            
        for r in rows:
            try:
                self.trigger_row_nbr = int(r.text)
            except ValueError:
                raise SpecificationError, "Invalid content '%s' for <row> element of <tabular_value> (must be a number)." \
                      % r.text
        if len(self.regexp) + len(self.match) + len(rows) == 0:            
            self.match.append("") # dummy match for tabular-data-only files

        n = e.findtext('skip')
        if n:
            self.trigger_skip_cnt = n
        n = e.findtext('pos')
        if n:
            self.pos = n
        n = e.findtext('rep')
        if n:
            self.rep = n
        ws = e.findtext('ws')
        if ws:
            self.ws = ws
        att = e.get('columns')
        self.nbr_columns = -1
        if att:
            self.nbr_columns = int(att)
            self.auto_columns = False
        else:
            self.auto_columns = True
        att = e.get('rows')
        if att:
            self.nbr_rows = int(att)
            if self.nbr_rows < 1:
                raise SpecificationError, 'Attribute "rows" has to be >= 1.'
        att = e.get('is_separator')
        if att and not cmp(lower(att), 'yes'):
            self.is_separator = True

        return

    def check_trigger(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        rval = "nothing"
        
        self.line_nbr = self.line_nbr + 1
        if self.trigger > 0:
            self.trigger = self.trigger - 1
        else:
            # First, check if we are still inside the table. Smarter checks
            # (like looking at the content of the columns and see if it matches the
            #  specified data type) will be applied in the future.
            if self.inside_table:
                continue_parsing = True
                if self.rows_parsed == self.nbr_rows:
                    if pb_debug:
                        print "#* parsed %d (of %d) rows - table is done" % (self.rows_parsed, self.nbr_rows)
                    self.inside_table = False
                    self.rows_parsed = 0
                    continue_parsing = False
                elif len(strip(get_dataline(fname, idx))) == 0:
                    if pb_debug:
                        print "#* found end of <tabular_location> (empty line)"
                    self.inside_table = False
                    continue_parsing = False
                elif self.nbr_columns != len(split(get_dataline(fname, idx), self.ws)):
                    if pb_debug:
                        print "#* found end of <tabular_location> (non-matching number of columns)"
                    self.inside_table = False
                    continue_parsing = False
                if continue_parsing:
                    self.trigger_cnt += 1
                    if pb_profiling:
                        t0 = time.clock() - t0
                        self.prof_data['check_trigger'].append(t0)
                    return "parse"
            # Now, check if a new table is triggered.
            if self.line_nbr == self.trigger_row_nbr:
                if pb_debug:
                    print "#* triggered <tabular_location> by row number"
                if self.is_separator and self.trigger_cnt > 0:
                    self.triggered_new_run = True
                self.trigger = self.trigger_skip_cnt
            for m in self.match:
                if find(get_dataline(fname, idx), m) != -1:
                    if pb_debug:
                        print "#* triggered <tabular_location> by match '%s'" % (m, )
                    self.trigger = int(self.trigger_skip_cnt)
                    if self.is_separator and self.trigger_cnt > 0:
                        self.triggered_new_run = True
                    break
            for r in self.regexp:
                if (r.search(get_dataline(fname, idx))):
                    if pb_debug:
                        print "#* triggered <tabular_location> by regexp '%s'" % (r, )
                    self.trigger = int(self.trigger_skip_cnt)
                    if self.is_separator and self.trigger_cnt > 0:
                        self.triggered_new_run = True
                    break

        if self.trigger == 0:
            # now on the first row of the data, reset trigger and start parsing
            self.trigger = -1
            self.rows_parsed = 0
            # determine nbr of columns if user didn't do so
            if self.nbr_columns == -1:
                self.nbr_columns = len(split(get_dataline(fname, idx), self.ws))
                if pb_verbose:
                    print "#* <tabular_location>: determined number of columns = %d" % self.nbr_columns
            # Check again if this row is a valid trigger. This is necessary for some rare cases,
            # i.e. an empty match definition, a trigger count of '0' and "garbage" at the end of
            # the data file.
            if len(split(get_dataline(fname, idx), self.ws)) == self.nbr_columns:
                self.inside_table = True
                self.trigger_cnt += 1
                if self.triggered_new_run:
                    rval = "new_run"
                else:
                    rval = "parse"

        if self.triggered_new_run:
            rval = "new_run"

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['check_trigger'].append(t0)

        return rval

    def parse_data(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()
        if pb_debug:
            print "#* parsing <tabular_location> in '%s'" % (rstrip(get_dataline(fname, idx)), )        

        rval = "store_set"
        # We increment 'self.rows_parsed' not here, but in get_value_contents(). This avoids a
        # problem that showed up when using tabular_locations with multiple input files: in this
        # case, it can happen that a line is triggered/parsed twice, but get_value_contents() is
        # called only the second time. For tables with defined number of rows, this would lead to
        # not importing one or more of the last table rows.
        self.contents = {}
        split_line = split(get_dataline(fname, idx), self.ws)
        prev_p = -1
        for v in self.names:
            if self.vpos.has_key(v):
                p = self.vpos[v]
                if p < 0:
                    p = prev_p - p

                if p >= len(split_line):
                    # Not enough colums in the table. This an error condition, as we shouldn't get
                    # here at all (nbr of columns is checked in 'check_trigger()')!
                    raise DataError, 'Not enough columns in parsed table'
                self.contents[v] = split_line[p]
                prev_p = p
            else:
                line_idx = 1 # content *after* match
                partial_line = split(get_dataline(fname, idx), self.vmatch[v], 1)
                if len(partial_line) > 1 and len(partial_line[line_idx]) > 0:
                    # remember first item behind
                    self.contents[v] = strip(partial_line[line_idx]).split()[0]
                    # need to set "prev_p" correctly
                    prev_p = len((partial_line[0] + self.vmatch[v]).split())
                else:
                    # no content found!
                    self.contents[v] = ""
                
            self.contents[v] = clean_string(self.contents[v])
            if self.contents[v] == "":
                # Protection against tables which have non-data in a similar format (the number
                # of columns) as the data itself. This will not be recognized as "end of table",
                # therefore it has to be ignored here.
                if pb_debug:
                    print "#* DEBUG: ignoring row due to invalid content of value %s." % v
                self.contents = {}
                rval = "nothing"

            if pb_debug:
                print "#* content for value %s: '%s'" % (v, self.contents[v])

            if self.filters[v] is not None:                
                self.contents[v] = ''.join(self.filters[v].split(self.contents[v]))
            
            if self.mappings.has_key(v):
                if self.mappings[v].has_key(self.contents[v]):
                    self.contents[v] = self.mappings[v][self.contents[v]]
                else:
                    for r in self.map_regexp[v]:
                        if r.search(self.contents[v]):
                            self.contents[v] = self.mappings[v][r]

            if self.is_numeric[v]:
                self.contents[v] = str_to_number(self.contents[v])
                if len(self.contents[v]) == 0:
                    # Empty content - but if this value has default content,
                    # and the user instructed us to use it, we do so.
                    if default_values[v] is None:
                        rval = "nothing"
                        break
                    else:
                        self.contents[v] = default_values[v]
                elif self.scale[v] is not None:
                    # datatype can be "integer(4)" or "integer(8)", so just compare first 7 characters.
                    if self.datatype[v][:7] == 'integer':
                        v_number = int(self.contents[v])
                        self.contents[v] = str(int(self.scale[v]*v_number))
                    else:
                        v_number = float(self.contents[v])
                        self.contents[v] = str(self.scale[v]*v_number)

            if pb_debug:
                print "   %s = %s" % (v, self.contents[v])

        if rval == "store_set":
            self.parse_cnt += 1
        
        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['parse_data'].append(t0)
            
        return rval

    def get_value_names(self):
        return self.names

    def get_value_contents(self, reset = True):
        if self.contents is not None:
            c = {}
            c.update(self.contents)
            # Unlike for named and explcit locations, we normally forget the data once it was
            # returned. This makes sense because the data will be stored after each row
            # of the table - and we want to store it only once on *that* occasion. If we
            # would not forget the data, we run into problems when parsing more than one
            # table per input file (because old values would reappear as 'zombie' values
            # when another table is triggered & parsed).
            # The only case when we do not want this behaviour is when another parameter is derived
            # from this data and has to call this function before the "offical" call. In this case,
            # it sets reset to False.
            if reset:
                self.contents.clear()
                self.contents = None
                # Only increment if the data is really delivered to be stored completely - not
                # if it only serves to calculate a derived parameter. See also comment on
                # self.rows_parsed in parse_data()
                self.rows_parsed += 1
            return c
        else:
            return None

    def drop_value(self, value_name):
        if self.names.count(value_name) == 0:
            raise DataError, "value '%s' can not be dropped as it does not exist" % value_name
        self.names.remove(value_name)
        return

    def new_run(self):
        self.line_nbr = 0
        if not self.triggered_new_run:
            # If the new run was triggered by this table, we do not want to restart
            # as we are right inside the table. Otherwise, we would only parse the
            # first row, and the trigger would not pop up on all following rows which
            # thus would be ignored.
            if self.auto_columns:
                self.nbr_columns = -1
            self.trigger = -1
            self.inside_table = False
            self.parse_cnt = 0
            self.trigger_cnt = 0
            
        self.triggered_new_run = False
        return True


class fixed_value(input_parse):
    def __init__(self, element_tree, parse_nodes, crs, value_name=None, value_content=None):
        """For a fixed value which is set via the command line ('-f a=b'), it is also
        possible to initialize via the name and content of a value."""
        input_parse.__init__(self, element_tree, parse_nodes, crs)

        self.type = 'fixed'
        self.only_once = True
        self.data_stored = False
        self.parse_cnt = 0
        self.trigger_cnt = 1
        
        if element_tree:
            self.name = None
            self.content = None

            r = element_tree
            n = r.findtext('name')
            if n:
                self.name = n
                # Check if this name is unique
                for pn in parse_nodes:
                    if pn.get_value_names(): # some parse nodes may return "None"!
                        for vn in pn.get_value_names():
                            if not cmp(vn, n):
                                raise SpecificationError, "value name '%s' was defined more than once." % vn
            else:
                raise SpecificationError, 'No value name provided for <fixed_value>.'
            n = r.findtext('content')
            if n:
                self.content = n
            else:
                raise SpecificationError, 'No content provided for <fixed_value>.'
        else:
            if not value_name or value_content == None:
                raise SpecificationError, 'No value name or content provided for <fixed_value>.'
            self.name = value_name
            self.content = value_content
        return

    def get_value_names(self):
        l = [ self.name ]
        return l

    def get_value_contents(self, reset = True):
        d = None
        if self.content is not None:
            d = { self.name:self.content }
            self.data_stored = True
        return d

    def check_trigger(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        rval = "nothing"
        # A fixed parameter is always able to be parsed and provide a value!
        self.trigger_cnt += 1

        if not self.data_stored:
            rval = "parse"

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['check_trigger'].append(t0)
        return rval

    def parse_data(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        self.parse_cnt += 1

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['parse_data'].append(t0)
        return "store_value"

    def new_run(self):
        if not self.data_stored:
            # data has not yet been delivered! Enforce it now.
            return False
        
        self.parse_cnt = 0
        self.trigger_cnt = 0
        self.data_stored = False
        return True


class set_separation(input_parse):
    def __init__(self, element_tree, parse_nodes, crs):
        input_parse.__init__(self, element_tree, parse_nodes, crs)

        self.type = 'separator'
        self.found = False
        self.skip = 0  # skip the first N separator marks (typically, the first one)
        
        r = element_tree
        n = r.findtext('match')
        if n:
            self.match = n
            self.regexp = None
        else:
            n = r.findtext('regexp')
            if n:
                self.match = None
                self.regexp = re.compile(n)
            else:
                raise SpecificationError, 'Invalid <set_separation> entry: contains no <match> or <regexp> entry)'

        n = r.findtext('skip')
        if n:
            self.skip = int(n)
        return

    def check_trigger(self, fname, idx):
        if pb_profiling:
            t0 = time.clock()

        rval = "nothing"
        if self.match:
            if find(get_dataline(fname, idx), self.match) != -1:
                rval = "parse"
        else:
            if re.search(self.regexp, get_dataline(fname, idx)):
                rval = "parse"
        if rval != "nothing":
            self.trigger_cnt += 1
            if self.skip > 0:
                if self.skip > 0:
                    rval = "nothing"
                self.skip -= 1

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['check_trigger'].append(t0)

        return rval

    def parse_data(self, fname, idx):
        # There is no data in this object, but we return 'new_run'.
        if pb_profiling:
            t0 = time.clock()

        self.parse_cnt += 1        

        if pb_profiling:
            t0 = time.clock() - t0
            self.prof_data['parse_data'].append(t0)
        return "new_run"

    def new_run(self):
        self.parse_cnt = 0
        self.trigger_cnt = 0
        return True

# global variables
exp_db = None            # database connection for this experiment
exp_crs = None           # database cursor for this experiment
inp_descs = []           # (name, src) of input description (src may be "xml" or "db")
inp_exp = None           # name of experiment to import data into
inp_synopsis = None      # run/input synopsis from XML file or command line
inp_description = None   # run/input description from XML file
inp_desc_tree = None     # XML tree
inp_desc_root = None     # XML root element
data_filenames = []      # names of the files to import data from
data_lines = {}          # maps filename to an array of lines that were read from this file
stdin_data = None        # data read from stdin (if any)
line_cnt = {}            # mapping of data filename to number of dta lines in the input file
enforce_file = {}        # force the import of a file? (maps filename to True or False)
data_inp_desc = {}       # mapping of data filename to input description
parsers = {}             # mapping of input description to parsers
dry_run = False
use_mtime = False
match_values = False
read_stdin = False
combine_input = False
value_is_multiple = {}   # mapping from value name -> boolean (multiple or only_once)
value_is_result = {}     # mapping from value name -> boolean (result or parameter)
fixed_values = {}
input_hashes = {}
valid_values = {}        # map value_name -> list of valid values for this value name
last_parsecnt = {}       # mapping from parser node to it's last parse count
default_values = {}      # mapping from value name -> default value (may be None)
valid_content = {}       # mapping from value name -> valid content (may be None)
is_numeric = {}
only_once = {}
derived_params = []
removed_pn = {}          # parse nodes which do no longer need to be considered for parsing the current run
#set_separation = None
dataset_idx = 0
perform_time = None
missing_action = 'abort'
all_exp_values = {}      # keys: all values defined in the experiment; content: data was stored (boolean)
cache_sz = 64*1024*1024
use_pset = []
store_pset = None
join_input = False
seq_input = False
pb_vfilename = "_pb_vfile_"
pb_debug = False
pb_verbose = False

db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }

# set value to '1' if a separate argument string follows this switch
valid_args = {'--dbhost=':0, '--dbport=':0, '--dbuser=':0, '--dbpasswd=':0,
              '--help':0, '--version':0, '--desc=':0, '--name=':0, '--exp=':0,
              '--test':0, '--attach=':0, '--synopsis=':0, '--missing=':0,
              '--verbose':0, '--debug':0, '--use-default':0, '--force':0,
              '--performed=':0, '--use-mtime':0, '--stdin':0, '--profile':0,
              '--maxmem=':0, '--enforce=':0, '--pset-store=':0, '--pset-use=':0,
              '--join': 0, '--sequential':0, '--sqltrace':0,
              '-V':0, '-v':0, '-h':0, '-d':1, '-n':1, '-e':1, '-s':1, '-u':0,
              '-a':1, '-f':1, '-t':0, '-b':1, '-p':1, '-m':0, '-i':0, '-j':0}


def print_help():
    """Print the specific help information for this tool."""
    print "perfbase input - Input new data ('runs') into an experiment"
    print "Usage:"
    print "  perfbase input [options] filename_1..filename_n"
    print "  (filename '-' reads from stdin)"  
    print "Options:"
    print "--desc=<file>, -d <file>    XML input description is stored in <file>"
    print "                            (multiple descriptions can be specfied; each is"
    print "                             applied to the input files that follow)"
    print "--join, -j                  Join all input files into a single 'virtual' input file; all data"
    print "                            will be stored in a single run."
    print "--sequential                Process multiple input files sequentially (not in parallel)"
    print "--name=<name>, -n <name>    Use input description <name> from experiment database"
    print "--exp=<exp>, -e <exp>       Input data into experiment <exp>"
    print "--synopsis=<syn>, -s <syn>  Synopsis of the data to be imported (single string)"
    print "--use-default, -u           Use default content for values where applicable"
    print "--stdin, -i                 Read parameter values not defined in input description from standard input"
    print "--missing=<action> -a <action>"
    print "                            Either 'ask' for any value from the experiment definition that has not"
    print "                            been set during parsing, use the 'default', 'abort' the import (default),"
    print "                            or 'ignore'"
    print "-f <v=c>                    Statically assign fixed content 'c' to value 'v'"
    print "--test, -t                  Do not import data into the database, only show what would be imported"
    print "--attach=<bin>, -b <bin>    Store (binary) attachment <bin> with this run"
    print "--force                     Process *all* input files, even those that have been recognized as existing"
    print "--enforce=<file>            Process *this* input file, even if it has been recognized as existing"
    print "--performed=<d>, -p <d>     Specify timestamp for the run(s)"
    print "--use-mtime, -m             Use the 'modify' timestamp of the input file for the run timestamp"
    print "--maxmem=<n>                Set max. amount of memory for input file caching to n MByte"
    print "--pset-store=<set>          Store only-once parameters in parameter set <set>"
    print "--pset-use=<set>[,<set>]    Use only-once parameters from one or more parameter sets <set>"
    print_generic_dbargs()


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global inp_descs, inp_exp, dry_run, missing_action
    global inp_synopsis, use_mtime, perform_time, read_stdin
    global valid_args, data_filenames, data_inp_desc, match_values, cache_sz
    global use_pset, store_pset, join_input, seq_input
    global db_info, pb_debug, pb_verbose

    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)
    force_all = False
    
    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVvd:n:e:s:uia:f:tb:p:mj', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                                            'help', 'version', 'desc=', 'name=', 'exp=',
                                                                            'test', 'attach=', 'verbose', 'debug', 'sqltrace',
                                                                            'use-default', 'force', 'performed=',
                                                                            'use-mtime', 'stdin', 'missing=', 'profile',
                                                                            'maxmem=', 'synopsis=', 'enforce=',
                                                                            'pset-store=', 'pset-use=', 'join',
                                                                            'sequential'])
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        exit(1)

    for o, v in options:
        n_params -= 1
        if o in ("-v", "--verbose"):
            set_verbose(True)
            continue
        if o == "--debug":
            set_debug(True)
            continue
        if o == "--sqltrace":
            set_sql_trace(True)
            continue
        if o == "--profile":
            set_profiling(True)
            continue
        if o in ("-h", "--help"):
            print_help()
            exit(0)
            continue
        if o in ("--version", "-V"):
            print_version()
            exit(0)
            continue

        if o in ("-d", "--desc"):
            # these are collected below
            n_params += 1
            continue
        if o in ("-n", "--name"):
            # these are collected below
            n_params += 1
            continue
        if o in ("-e", "--exp"):
            inp_exp = v
            continue
        if o in ("-j", "--join"):
            join_input = True
            continue
        if o == "--sequential":
            seq_input = True
            continue
        if o in ("-s", "--synopsis"):
            inp_synopsis = v
            continue        
        if o == "--enforce":
            # these are collected below
            n_params += 1
            continue
        if o == "--pset-store":
            store_pset = v
            missing_action = 'ignore'
            continue
        if o == "--pset-use":
            use_pset.extend(split(v, ','))
            continue
        if o == "-b" or o == "--attach":
            inp_attachment = v
            continue
        if o == "-f":
            all_vals = split(v, ',')
            for single_val in all_vals:
                fval = split(single_val, '=')
                if len(fval) != 2:
                    print "#* ERROR: invalid argument '%s' to '%s' option" % (v, o)
                    exit(1)
                fixed_values[fval[0]] = fval[1]
            continue
        if o in ("-t", "--test"):
            dry_run = True
            continue
        if o in ("-u", "--use-default"):
            match_values = True
            continue
        if o in ("-a", "--missing"):
            missing_action = v
            if not missing_action in ('ignore', 'abort', 'ask', 'default'):
                print "#* ERROR: invalid argument '%s' to '%s' option" % (v, o)
                exit(1)
            continue        
        if o in ("-i", "--stdin"):
            read_stdin = True
            continue
        if o == "--force":
            force_all = True
            continue
        if o in ("-m", "--use-mtime"):
            use_mtime = True
            continue
        if o in ("-p", "--performed"):
            perform_time = v
            continue
        if o == "--maxmem":
            try:
                cache_sz = int(v)*1024*1024
            except ValueError:
                print "#* ERROR: invalid argument '%s' to option --maxmem" % v
                exit(1)
            continue

        if o == "--dbhost":
            db_info['host'] = v
            continue
        if o == "--dbport":
            try:
                db_info['port'] = int(v)
            except ValueError:
                print "#* ERROR: invalid argument '%s' to option --dbport" % v
                exit(1)
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    pb_debug = do_debug()
    pb_verbose = be_verbose()

    if pb_verbose and inp_synopsis is not None:
        print "#* using synopsis '%s'" % inp_synopsis
    
    # There's a problem with multiple input files: does each input file represent a different
    # run, or do they contain data that is to be combined for a single run? The user has
    # to indicate which of these possibilities does apply.
    data_filenames = []
    # We also need to map the data filenames to the name of the input description used to
    # process it.
    current_inp_desc = None
    if len(inp_descs) > 0:
        current_inp_desc = inp_descs[0]
    idx = 0
    while idx < len(argv2):
        a = argv2[idx]
        arg_switch = get_switch(valid_args, a)
        if not arg_switch and not valid_args.has_key(a):
            # An argument that does (directly) belong to a switch - must be
            # a name of a data file.
            data_filenames.append(a)
            data_inp_desc[a] = current_inp_desc
            enforce_file[a] = force_all
            if a == '-':
                # Required fix because this character is not processes as an option in the loop above.
                n_params = n_params - 1
        if arg_switch:
            if arg_switch == "--enforce=":
                n_params -= 1
                inp_fname = a[len("--enforce="):]
                data_filenames.append(inp_fname)
                data_inp_desc[inp_fname] = current_inp_desc
                enforce_file[inp_fname] = True
            elif arg_switch == "--desc=":
                n_params -= 1
                current_inp_desc = a[len("--desc="):]
                inp_descs.append((current_inp_desc, "xml"))
            elif arg_switch == "-d":
                n_params -= 1
                idx += 1
                current_inp_desc = argv2[idx]
                inp_descs.append((current_inp_desc, "xml"))
            elif arg_switch == "--name=":
                n_params -= 1
                current_inp_desc = a[len("--name="):]
                inp_descs.append((current_inp_desc, "db"))
            elif arg_switch == "-n":
                n_params -= 1
                idx += 1
                current_inp_desc = argv2[idx]
                inp_descs.append((current_inp_desc, "db"))
            else:
                # One of the switches that have already been processed above.
                # Skip potential parameter of this switch.
                idx += valid_args[arg_switch]
                
        idx += 1

    if n_params != 0:
        raise StandardError, "Syntax error in command line (need to use '\".. ..\"' to quote multi-word arguments?)"

    if join_input:
        enforce_file[pb_vfilename] = force_all

    if len(data_filenames) == 0:
        print "#* ERROR: no input file specified"
        print "   Use option '--help' for help."
        exit(1)

    if pb_verbose:
        print "#* importing data from"
        for f in data_filenames:
            print "    %s (parsed according to %s)" % (f, data_inp_desc[f])

    if len(inp_descs) == 0:
        print "#* ERROR: no input description specified"
        print "   Use option '--help' for help."
        exit(1)
    return


def parse_input_specs():
    """Transform the XML input specification into an internal representation for parsing a data file"""
    global inp_descs, inp_exp, dry_run, inp_synopsis, inp_description
    global db_info, exp_db, exp_crs, value_is_multiple
    global parsers, match_values, read_stdin, derived_params, use_pset, all_exp_values

    inp_descs_fnames = []    
    inp_desc_roots = {}
    inp_desc_trees = {}

    # First, process all information from the XML files located in the file system. We need
    # i.e. to know the experiment name to access the database.
    for inp in inp_descs:
        if inp[1] != "xml":
            continue
        if pb_verbose:
            print "#* Parsing input description from XML file", inp[0]
        if access(inp[0], F_OK|R_OK) == False:
            raise SpecificationError, "can not access input description '%s'" % inp[0]
        inp_desc_trees[inp[0]] = ElementTree.parse(inp[0])
        inp_desc_roots[inp[0]] = inp_desc_trees[inp[0]].getroot()
        if inp_desc_roots[inp[0]].tag != "input":
            raise SpecificationError, "%s is not a perfbase input description." % (inp[0])

    # Determine the experiment and database and make sure it can be accessed.
    if not inp_exp:
        if len(inp_desc_roots) > 0:
            # Try to retrieve experiment name from XML description.
            for xml_tree in inp_desc_trees.itervalues():
                exp = xml_tree.findtext('experiment')
                if exp:
                    if not inp_exp:
                        inp_exp = exp
                    elif exp != inp_exp:
                        raise SpecificationError, "inconsistent <experiment> contents (%s vs. %s)" % (exp, inp_exp)
        if not inp_exp:
            # Last resort: use default experiment from environment
            inp_exp = getenv("PB_EXPERIMENT")
            if not inp_exp:
                raise SpecificationError, "experiment name is not specified"

    # Open the experiment database
    # Determine the database server to be used. Preference of the parameters:
    # cmdline > xml_file > environment > default
    db_info['name'] = get_dbname(inp_exp)
    xml_tree = None
    for xml_tree in inp_desc_trees.itervalues():
        # Use the first <database> entry that is found. Consistency
        # check would be complicated here - is it necessary?
        if xml_tree.find('database'):
            break
    get_dbserver(xml_tree, db_info)
    exp_db = open_db(db_info, exp_name=inp_exp)
    if exp_db is None:
        exit(1)
    if not check_db_version(exp_db, inp_exp):
        raise DatabaseError, "version mismatch of experiment database and commandline tools"
    exp_crs = exp_db.cursor()

    # Get input descriptions from attachments.
    for inp in inp_descs:
        if inp[1] != "db":
            continue
        if pb_verbose:
            print "#* Parsing input description from attachment", inp

        # Check if attachment is an input description and store it in a temporary file.
        if get_attachment_type(exp_crs, inp[0]) != "input":
            raise SpecificationError, "attachment '%s' is not an input description." % (inp[0])

        # This file will be deleted upon exit.
        # XXX NamedTemporaryFile() may not work properly under Windows!
        tmp_file = tempfile.NamedTemporaryFile(mode='w', prefix='pb_')
        if not dump_attachment(exp_crs, inp[0], tmp_file):
            raise DataError, "could not dump attachment '%s' to temporary file '%s'" % (inp[0], tmp_file.name)
        inp_desc_trees[inp[0]] = ElementTree.parse(tmp_file.name)
        inp_desc_roots[inp[0]] = inp_desc_trees[inp[0]].getroot()

    #
    # Now, the parsing starts.
    #
    # If applicable, create fixed values for the data found within a parameter set.
    for pset in use_pset:
        if len(pset) == 0:
            print "#* WARNING: empty dataset name (check comma with pset-use)"
            continue
        pset_cntnt = get_pset(exp_crs, pset)
        if pset_cntnt is None:
            raise SpecificationError, "parameter set '%s' is not defined in this experiment." % (pset, )
        # We need to work with the "real" names of the parameters, not the SQL-deformed ones
        sqlexe(exp_crs, "SELECT name FROM exp_values WHERE is_result = 'f' AND only_once = 't'")
        for r in exp_crs.fetchall():
            real_pname = r[0]
            sql_pname = real_pname.lower()
            if pset_cntnt.has_key(sql_pname):
                if not fixed_values.has_key(real_pname):
                    fixed_values[real_pname] = str(pset_cntnt[sql_pname])

    # The input specifications can be supplied in different ways, with this priority:
    # 1. --desc option on the command line (read from file)
    # 2. --name option on the commandl line (read from database)
    # 3. no options (read default input description from database)
    if len(inp_desc_roots) == 0:
        # Input description has to be retrieved from the database
        print "#* ERROR: retrieving input description from database is not yet implemented."
        exit(1)                

    # Create one parser for each input description.
    for k, v in inp_desc_roots.iteritems():
        # Description and synopsis for this run
        # Synopsis and description are shared by all input descriptions. We
        # use the one provided by the commandline, or the first found in any of
        # the descrptions.
        if not inp_synopsis:
            inp_synopsis = v.findtext('synopsis')
        if not inp_synopsis:
            inp_synopsis = ""
        if not inp_description:
            inp_description = v.findtext('description')
        if not inp_description:
            inp_description = ""

        # Create a class instance for each of the user-defined "parse events", and store
        # them in a list.
        parsers[k] = parser_nodes()

        for location_type in ('named_location', 'filename_location', 'explicit_location',
                               'tabular_location', 'fixed_value', 'split_location'):
            inp_nodes = v.findall(location_type)
            for n in inp_nodes:
                parsers[k].n_nodes += 1
                try:
                    pn = eval(location_type)(n, parsers[k].nodes, exp_crs)
                except SpecificationError, error_msg:
                    print "#* ERROR: failed to initialize <%s>. Exiting." % location_type
                    print error_msg
                    exit(1)
                # Check if this values conflicts with a fixed value.
                for vn in pn.get_value_names():
                    if fixed_values.has_key(vn):
                        pn = None
                        break
                if pn:
                    if pb_debug:
                        print "DEBUG: adding parse node '%s' for %s" % (location_type, pn.get_value_names())
                    parsers[k].nodes.append(pn)

            if location_type == 'fixed_value':
                # Also add the fixed values that have been specified on the command line. They
                # override the specifications in the XML file. It is suffient to add the fixed
                # values to the first parser only as the data is gathered across all parsers.
                for k_pars in parsers.iterkeys():
                    for k_fix, v_fix in fixed_values.iteritems():
                        pn = fixed_value(None, exp_crs, parsers[k_pars].nodes, k_fix, v_fix)
                        parsers[k_pars].nodes.append(pn)
                    break

        inp_nodes = v.findall('set_separation')
        if inp_nodes:
            if len(inp_nodes) > 1:
                print "#* ERROR: more than one <set_separation> specification."
                exit(1)
            try:
                pn = set_separation(inp_nodes[0], parsers[k].nodes, exp_crs)
            except SpecificationError, error_msg:
                print "#* ERROR: failed to initialize <set_separation>. Exiting."
                print error_msg
                exit(1)
            parsers[k].nodes.append(pn)

    # 'derived_parameters' are derived from *all* parameters. For the case of
    # multiple input description files, we need to make sure that the derived parameter
    # is able to gather information from all of them. Therefore, they have to be initialized
    # separately.
    for k, v in inp_desc_roots.iteritems():
        for n in v.findall('derived_parameter'):
            parsers[k].n_nodes += 1
            # Need to see *all* parse nodes!
            all_parse_nodes = []
            for k1, v1 in inp_desc_roots.iteritems():
                all_parse_nodes.extend(parsers[k1].nodes)
            try:
                pn = derived_parameter(n, all_parse_nodes, exp_crs)
            except SpecificationError, error_msg:
                print "#* ERROR: failed to initialize <derived_parameter>. Exiting."
                print error_msg
                exit(1)
            # Check if this values conflicts with a fixed value.
            for vn in pn.get_value_names():
                if fixed_values.has_key(vn):
                    pn = None
                    break
            if pn:
                if pb_debug:
                    print "DEBUG: adding parse node '%s' for %s" % (location_type, pn.get_value_names())
                parsers[k].nodes.append(pn)
                derived_params.append(pn)

    # Check the values from the input specifications with the values specified in the
    # experiment database.
    # First:  check if the user specfied values not defined for this experiment,
    all_vns = {}
    pns_to_remove = []
    for k in parsers.iterkeys():
        for pn in parsers[k].nodes:
            if pn.get_value_names(): # i.e. set_separation returns "None" here!
                for vn in pn.get_value_names():
                    all_vns[vn] = 1   # this dictionary is needed below
                    sqlexe(exp_crs, "SELECT name FROM exp_values WHERE (name = '%s')" % vn)
                    if exp_crs.rowcount == 0:
                        if match_values:
                            pns_to_remove.append(pn)
                        else:
                            raise SpecificationError, "value '%s' is not defined in this experiment." % (vn, )
        for pn in pns_to_remove:
            parsers[k].nodes.remove(pn)

    # Next: check if values defined for this experiment are missing from this
    # input spec. In this case, default values are to be used if defined in the
    # experiment, if requested by the user.
    sqlexe(exp_crs, "SELECT * FROM exp_values")
    nim = build_name_idx_map(exp_crs)
    db_rows = exp_crs.fetchall()
    missing_defs = []
    for db_row in db_rows:
        val_name = db_row[nim['name']]
        default_values[val_name] = db_row[nim['default_content']]
        value_is_multiple[val_name] = not db_row[nim['only_once']]
        value_is_result[val_name] = db_row[nim['is_result']]
        valid_content[val_name] = db_row[nim['valid_values']]

        if not all_vns.has_key(val_name):
            # try to use default value
            if match_values:
                if not default_values[val_name] is None:
                    # create a <fixed_value>
                    for v in parsers.itervalues():
                        v.nodes.append(fixed_value(None, exp_crs, v.nodes, val_name, default_values[val_name]))
                else:
                    # no default value available - problem!
                    raise SpecificationError, " value '%s' has no default value, can not be matched." \
                          % (val_name, ) 
            elif read_stdin:
                val_str = read_value_content(val_name, exp_crs)
                # Next line is only necessary for 'None' default values - in this case, nothing is
                # stored in the database, but we need to remember that this is what the user wanted.
                all_exp_values[val_name] = True
                for v in parsers.itervalues():
                    v.nodes.append(fixed_value(None, exp_crs, v.nodes, val_name, val_str))
            else:
                missing_defs.append(val_name)
    if len(missing_defs) > 0 and not store_pset:
        print "#* Missing input definition(s): value [default content] {valid content}:"
        for v in missing_defs:
            print "    %s" % (v),
            if default_values[v] is not None:
                print " [%s]" % default_values[v],
            if valid_content[v] is not None:
                print " %s" % valid_content[v]
            else:
                print " {}"
        print "   Try option '--use-default' or '--stdin'."
        raise SpecificationError, "Missing input definitions."

    return parsers


def get_dataline(data_src, idx):
    if isinstance(data_src, list):
        # This applies when filenames are parsed (the filename is passed as a pseudo-line)
        return data_src[idx-1]
    elif data_src in data_lines:
        # file or stdin that have been read into memory at startup. Index starts at 0.
        return data_lines[data_src][idx-1]
    else:
        if False:
            # For the linecache module, the index starts at 1
            l = getline(data_src, idx)
        else:
            # Alternatively, use the simple caching by perfbase itself.
            l = rdline(data_src, idx)
        if len(l) == 0:
            # EOF
            raise IndexError, "read past end of file"
        return l


def create_runtable(crs, fnames):
    """Create a new entry in the run metatable, and determine the index of the run."""
    global inp_desc_xml, inp_desc_db, inp_exp, inp_synopsis, inp_description
    global input_hashes, perform_time, db_info, use_mtime
    global exp_db
    
    if store_pset is not None:
        # Data will only be stored in the parameter-set table.
        return (0, None)

    file_mtimes = {}
    for f in fnames:
        if f not in ('-', pb_vfilename):
            # We have to cut off the time zone information because under Windows, it contains redundant garbage
            # that PostgreSQL does not understand. For now, only use date and time information.
            # XXX Apply under Windows only, or fix it there somehow.
            mtime = secs_to_timestamp(os.stat(f)[stat.ST_MTIME]).split()            
            file_mtimes[f] = mtime[0] + " " + mtime[1]
        else:
            # stdin has a timestamp of "now"
            file_mtimes[f] = mk_timestamp()
    create_time = mk_timestamp()
    if not perform_time:
        if use_mtime:
            # we use the oldest mtime of all input files
            for f in fnames:
                if perform_time == None:
                    perform_time = file_mtimes[f]
                    continue
                if perform_time < file_mtimes[f]:
                    perform_time = file_mtimes[f]
        else:
            perform_time = mk_timestamp()
    run_key = randint(0,1000000000)

    # create array strings - create a function for this!?
    tmp_str = "{ "
    for f in fnames:
        tmp_str += str(input_hashes[f]) + ","
    hash_str = tmp_str[:-1] + "}"
    tmp_str = "{ "
    for f in fnames:
        tmp_str += realpath(f) + ","
    fname_str = tmp_str[:-1] + "}"
    tmp_str = "{ "
    for f in fnames:
        tmp_str += str(file_mtimes[f]) + ","
    mtime_str = tmp_str[:-1] + "}"

    if inp_synopsis == '-':
        # read synopsis from stdin
       inp_synopsis = read_from_stdin("Enter synopsis:")

    if inp_description == '-':
        # read description from stdin
       inp_description = read_from_stdin("Enter description:")
    
    # new entry in meta-table for all runs
    sqlexe(crs, """INSERT INTO run_metadata
    (creator, created, performed, key, active, synopsis, description, input_name, input_hash, input_mtime, nbr_inputs)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", None,
           (db_info['user'], create_time, perform_time, str(run_key), "t",
            inp_synopsis, inp_description, fname_str, hash_str, mtime_str,
            str(len(fnames))))
    # XXX: Handle the case of an already existing random key!
    
    # Retrieve index for the just created entry. We can not just use the "largest" ID,
    # as another run might be created concurrently. For now, we rely on the
    # timestamp + random number being unique. Should be enough?
    sqlexe(crs, "SELECT index FROM run_metadata WHERE (created = '%s' AND key = '%s')" % (create_time, run_key))
    nim = build_name_idx_map(crs)
    if crs.rowcount > 1:
        raise DatabaseError, "Multiple runs with identical timestamps & key."
    if crs.rowcount == 0:
        raise DatabaseError, "No run with matching timestamp & key."
    db_row = crs.fetchone()
    run_idx = db_row[nim['index']]

    # Check if we need to create a 'rundata_once' entry.
    sqlexe(crs, "SELECT * FROM exp_values WHERE only_once = 't'")
    if crs.rowcount > 0:
        sqlexe(crs, "INSERT INTO rundata_once ( run_index ) VALUES ( %s )", None, (str(run_idx), ))

    fix_access_rights(crs, run_idx)

    if pb_verbose:
        print "#+ Creating new run with index %d" % run_idx
    
    return run_idx


def read_value_content(value_name, crs):
    """Read a value content from standard input."""
    global all_exp_values
    
    sqlexe(crs, "SELECT * FROM exp_values WHERE name = '%s'" % value_name)
    if crs.rowcount == 0:
        return None
    nim = build_name_idx_map(crs)
    db_row = crs.fetchone()
    
    prompt_str = "%s = ? " % value_name
    dflt = db_row[nim['default_content']]
    #if dflt is not None and len(dflt) > 0 :
    if dflt is not None:
        # default value used when nothing is entered
        prompt_str += "[%s] " % dflt
    valid_vals = None
    if db_row[nim['valid_values']] != None:
        valid_vals = db_row[nim['valid_values']]
        for idx in range(len(valid_vals)):
            prompt_str += "%d:%s " % (idx+1, valid_vals[idx].strip('"'))
    val_str = ""
    while len(val_str) == 0:
        val_str = raw_input(prompt_str)
        if len(val_str) == 0 and dflt is not None:
            val_str = dflt
            print " -> %s" % val_str
            break
        if len(val_str) > 0 and valid_vals != None:
            try:
                idx = int(val_str)-1
            except ValueError:
                print "Invalid input '%s'. Please enter the index of the chosen content." % val_str
                val_str = ""
                continue
            try:
                val_str = valid_vals[idx].strip('"')
            except IndexError:
                print "Invalid index %d (needs to be >= 1 and <= %d)" % (idx+1, len(valid_vals))
                val_str = ""
                continue
            print " -> %s" % val_str
            break

    return val_str


def check_missing(crs, fnames, idx):
    """Check if all values of the expirement have been assigned some contents in this
    parsing pass."""
    # XXX Currently, this works only for singular values (which are not part of a data set),
    # but this is the most typical case. Extending for data sets is possible, but some more
    # effort.
    global debug, dry_run, derived_params, match_values, default_values, missing_action
    global value_is_multiple, all_exp_values

    have_stored_data = True

    # Check for missing value content of onlyonce -values.
    missing_values = []
    for k, v in all_exp_values.iteritems():
        if not v and not value_is_multiple[k]:
            missing_values.append(k)

    if len(missing_values) > 0:
        if missing_action in ('abort', 'ignore', 'default'):
            if match_values or missing_action == 'default':
                stored_values = []
                for m in missing_values:
                    if default_values[m] != None:
                        put_datavalue(m, default_values[m], crs, idx)
                        stored_values.append(m)
                for v in stored_values:
                    missing_values.remove(v)
            if len(missing_values) > 0:
                if missing_action in ('abort', 'default'):
                    print "#* ERROR: No content was found, and no default content provided for at least one value."
                    print "   Input file(s):", fnames
                    print "   Value names:"
                    for v in missing_values:
                        print "    %s" % v
                    print "   No data written to database."
                    have_stored_data = False
                else:
                    if pb_verbose:
                        print "#* No content for", missing_values, "from input file(s)", fnames
                    have_stored_data = True
        elif missing_action == 'ask':
            # Query the user for missing content of values. 
            print "#* No content was found for at least one value."
            print "   Input file(s):", fnames
            print "   Value names:"
            for m in missing_values:
                print "    %s" % m
            print "   Add content for these values now? <YES/no>"
            if strip(upper(sys.stdin.readline())) == "NO":
                print "   No data written to database."
                have_stored_data = False
            else:
                for m in missing_values:
                    content = read_value_content(m, crs)
                    put_datavalue(m, content, crs, idx)
                have_stored_data = True
        
    # reset flags
    for k in all_exp_values.iterkeys():
        all_exp_values[k] = False        
    
    return have_stored_data


def put_dataset(dataset, crs, run_idx, update={}):  
    global all_exp_values, dry_run, dataset_idx
    global store_pset

    if store_pset is not None:
        # When storing a parameter set, we do not store any data in "run" tables
        # as we are actually not creating a run!
        # XXX What about only-once parameters inside a dataset?
        return
    if len(dataset) == 0:
        # This may happen - just ignore empty datasets.
        return
        
    if dry_run:
        # print value content to stdout
        print "Dataset %d in run %d" % (dataset_idx, run_idx)
        dataset_idx += 1
        print dataset
        return

    # CHECK: this should be done when parsing the input XML, if possible
    update_mode = None
    for v in update.itervalues():
        if update_mode is not None and v != update_mode:
            raise SpecificationError, "inconsistent 'update' attributes"
        update_mode = v

    val_content = {}
    val_update = {}
    content_len = 0
    for k, v in dataset.iteritems():
        if v is not None:
            v_str = str(v)
            if is_numeric[k] and len(v_str) == 0:
                # zero-length number strings will raise SQL errors
                # CHECK: how can we have a zero-length string here?
                continue
            all_exp_values[k] = True

            if update.has_key(k):
                val_update[k] = v_str
            else:
                val_content[k] = v_str
                           
    have_data = True
    do_insert = True
    if len(val_update) > 0:
        if update_mode == "auto":
            # We need to insert the data normally in case it does not exist. 
            # Implementation of this feature requires a separate query.
            sql_str = "SELECT * FROM rundata WHERE "
            for k,v in val_update.iteritems():
                sql_str += "%s = '%s' AND " % (k, v)
            sql_str = rstrip(sql_str, " AND ")
            sqlexe(crs, sql_str)
            if crs.rowcount > 0:
                # UPDATE possible
                do_insert = False            
                val_update["pb_run_index"] = str(run_idx)
            else:
                val_content.update(val_update)
        else:
            # always UPDATE - no matter is there actually is a value set to be updated
            do_insert = False
    
    if do_insert:
        val_content["pb_run_index"] = str(run_idx)

        sql_str = "INSERT INTO rundata ("
        for k in val_content.iterkeys():
            sql_str += "%s," % (k, )
        sql_str = rstrip(sql_str, ",") + ") VALUES ("
        for v in val_content.itervalues():
            sql_str += "'%s'," % (v, )
        sql_str = rstrip(sql_str, ",") + ")"

        if len(val_content) == 1:
            have_data = False
    else:
        sql_str = "UPDATE rundata SET "
        for k,v in val_content.iteritems():
            sql_str += "%s = '%s'," % (k, v)
        sql_str = rstrip(sql_str, ",") + " WHERE "
        for k,v in val_update.iteritems():
            sql_str += "%s = '%s' AND " % (k, v)
        sql_str = rstrip(sql_str, " AND ")        

        if len(val_content) == 0:
            have_data = False

    # It happens that a data set is triggered to be stored without actually containing any
    # relevant data (due to "corrupted" input files, where i.e. numbers can not be parsed from text).
    # To avoid SQL errrors, such datasets are not stored at all - this is safe, as no information is
    # lost.
    if have_data:
        try:
            sqlexe(crs, sql_str, "#* Storing dataset by '%s'" % (sql_str,))
        except psycopg.Error, error_message:
            print error_message
            exit(1)

    return


def store_dataset(parse_nodes, crs, run_idx):
    """Store a dataset (all values which do not occur only once) in the experiment database"""
    global valid_values, last_parsecnt

    if pb_debug:
        print "#* storing dataset"

    # Access database. Although we store a dataset, it is not necessarily true that
    # all data to be stored has "occurrence=multiple". It is also possible that within
    # a tabular dataset, "occurrence=once" values are hidden. This is rare, but may make
    # sense for certain situations and should be supported.
    dataset = {}
    v_updates = {}
    for pn in parse_nodes:
        if pn in removed_pn:
            continue
        if isinstance(pn, fixed_value):
            continue
        
        has_new_data = True
        if not last_parsecnt.has_key(pn):
            last_parsecnt[pn] = pn.get_parse_count()
        else:
            if last_parsecnt[pn] == pn.get_parse_count():
                # no new data to be stored
                has_new_data = False
            else:
                last_parsecnt[pn] = pn.get_parse_count()

        v_names = pn.get_value_names()
        v_contents = pn.get_value_contents()
        if v_contents is not None:
            v_updates.update(pn.get_update_values())

        if pb_debug:
            print "#* dataset is ", v_names, v_contents
            print "#* updates are ", v_updates
        if not v_contents:
            continue
        for vn in v_names:
            if valid_values[vn] and valid_values[vn].count(v_contents[vn]) == 0:
                raise DataError, "invalid content '%s' for value '%s'" % (v_contents[vn], vn)
            if value_is_multiple[vn]:
                if v_contents.has_key(vn) and not dataset.has_key(vn):
                    # We don't want to overwrite existing content. This does not solve the
                    # problem of which content to use in case of a conflicht (the first or the latest)?
                    # This should best be managed by the query itself, at least for now.
                    dataset[vn] = v_contents[vn]
                else:
                    if pb_verbose:
                        print "#* WARNING: incomplete dataset (no content for '%s')" % vn
                    dataset[vn] = None
            elif v_contents.has_key(vn) and has_new_data:
                put_datavalue(vn, v_contents[vn], crs, run_idx)

    put_dataset(dataset, crs, run_idx, v_updates)
    return


def merge_and_store_dataset(parsers, crs, run_idx):
    """Gather data from different parsers, and merge it into a single dataset
     that is stored in the database. Check for inconsistencies on this occasion."""
    global data_filenames, data_inp_desc, last_parsecnt

    if pb_debug:
        print "#* merging and storing dataset"

    # create merged dataset
    dataset = {}
    for fname in data_filenames:
        for pn in parsers[data_inp_desc[fname]].nodes:
            if pn in removed_pn:
                continue
            if isinstance(pn, fixed_value):
                continue

            has_new_data = True
            if not last_parsecnt.has_key(pn):
                last_parsecnt[pn] = pn.get_parse_count()
            else:
                if last_parsecnt[pn] == pn.get_parse_count():
                    # no new data to be stored
                    has_new_data = False
                else:
                    last_parsecnt[pn] = pn.get_parse_count()

            v_names = pn.get_value_names()
            v_contents = pn.get_value_contents()
            if v_contents:
                for n in v_names:
                    if valid_values[n] and valid_values[n].count(v_contents[n]) == 0:
                        raise DataError, "invalid content '%s' for value '%s'" % (v_contents[n], n)
                    if value_is_multiple[n]:
                        if dataset.has_key(n):
                            if dataset[n] != v_contents[n]:
                                print "#* ERROR: inconsistent content for value '%s' (from %s)" % (n, fname)
                                print "   current content:", dataset[n]
                                print "       new content:", v_contents[n]
                                exit(1)
                        else:
                            dataset[n] = v_contents[n]
                            if pb_debug:
                                print "  Setting %s\t= %s" % (n, v_contents[n])
                    elif v_contents.has_key(n) and has_new_data:
                        put_datavalue(n, v_contents[n], crs, run_idx)
    
    put_dataset(dataset, crs, run_idx)
    return


def put_datavalue(vname, vcontent, crs, idx):
    global dry_run, all_exp_values

    if len(str(vcontent)) == 0:
        # Storing 0-length data can only occur for an empty default value (definition
        # '<default></default>'); and in this case, we do not touch the database.
        return
    if store_pset is not None:
        # If it's an only-once parameter, we store it within the specified parameter set.
        if not (value_is_result[vname] or value_is_multiple[vname]):
            store_in_pset(crs, store_pset, vname, vcontent)
        return

    all_exp_values[vname] = True

    if dry_run:
        print "Storing single value(s) in run ", idx
        print "  %s\t= %s" % (vname, vcontent)
        return

    try:
        sqlexe(crs, "UPDATE rundata_once SET %s = '%s' WHERE run_index = %d" % (vname, vcontent, idx),
               "storing data value:")
    except psycopg.Error, error_message:
        print error_message
        exit(1)
    
    return


def store_datavalue(parse_node, crs, idx):
    """Store a single value (occuring only once in an experiment)"""
    global valid_values, last_parsecnt
    
    v_names = parse_node.get_value_names()
    v_contents = parse_node.get_value_contents()    
    if not v_contents:
        n = ""
        for v in v_names:
            n += " "+v
        raise DataError, "no data available when storing single value(s): %s" % n
    
    for n in v_names:
        if value_is_multiple[n]:
            # needs to be stored together with the rest of the dataset!?
            return
    last_parsecnt[parse_node] = parse_node.get_parse_count()
        
    for n in v_names:
        if valid_values[n] and valid_values[n].count(v_contents[n]) == 0:
            # check for allowed NULL content which is expressed differently in the
            # default content and the valid_values:
            if len(v_contents[n]) == 0 and valid_values[n].count('None') > 0:
                continue
            raise DataError, "invalid content '%s' for value '%s'" % (v_contents[n], n)

    for n in v_names:
        put_datavalue(n, v_contents[n], crs, idx)

    return


def parse_filename(fname, parsers, run_idx, crs):
    global match_values, default_values

    have_stored_data = False
    fname_list = [ fname ]

    if pb_debug:
        print "#* DEBUG: parse_filename() for ", fname

    for pn in parsers[data_inp_desc[fname]].nodes:
        if not pn.get_value_names(): # some parse nodes may return "None"!
            continue
        v_name = (pn.get_value_names())[0]
        if isinstance(pn, filename_location):
            if pb_debug:
                print "#* DEBUG: checking filename for ", pn.get_value_names()
            if pn.check_trigger(fname_list, 0) == "parse":
                if pn.parse_data(fname_list, 0) == "store_value":
                    store_datavalue(pn, crs, run_idx)
                    have_stored_data = True
                else:
                    print "#* WARNING: found invalid data for '%s' in <filename_location> (filename %s)" \
                          % (v_name, fname)
            else:
                if match_values and not default_values[v_name] is None:
                    # use default value
                    put_datavalue(v_name, default_values[v_name], crs, run_idx)
                    have_stored_data = True

    return have_stored_data


def parse_datafiles(data_filenames, parse_nodes, crs):
    """Retrieve data from a data file according to the input specification."""
    global db_info
    global derived_params, match_values, default_values
    global dataset_idx, dry_run, debug, last_parsecnt, removed_pn
    global seq_input, line_cnt

    # Number of data files (sources) which get merged into a single run table.
    unique_inp_desc = {}
    for v in data_inp_desc.itervalues():
        if not unique_inp_desc.has_key(v):
            unique_inp_desc[v] = True
    n_data_sources = len(unique_inp_desc)

    # We parse the files line by line, and call 'check_trigger()' of all parse objects
    # (associated to this file) for each line. If a trigger applies, we let the same object
    # parse the line. If necessary (indicated by the StoreDataset exception), we store the
    # current dataset to the experiment database (or print it to stdout).
    have_stored_data = False
    line_idx = {}
    first_pass = {}
    for fname in data_filenames:
        line_idx[fname] = 1

    run_idx = -1
    run_cnt = 0  # number of runs already created
    parse_next_file = True
    create_new_table = True
    stop_parsing = False
    action = "new_run"
    removed_pn = {}

    t0 = time.clock()

    while not stop_parsing and parse_next_file:
        # loop over all files 
        for f_idx in range(len(data_filenames)):
            fname = data_filenames[f_idx]
            if pb_verbose or pb_debug:
                print "#* Processing data file ", fname
            
            # With only one data source, each new data file is a new run.
            # Otherwise, a new table is created only for the first pass of the
            # first data file.
            if n_data_sources == 1 or (f_idx == 0 and create_new_table):
                removed_pn = {}
                for p in parsers[data_inp_desc[fname]].nodes:
                    while not p.new_run() and run_idx >= 0:
                        # can only occur with "only_once" values (counters)
                        store_datavalue(p, crs, run_idx)
                last_parsecnt.clear()
                
                if n_data_sources == 1:
                    if not dry_run:
                        f = data_filenames[f_idx:f_idx+1]
                        if run_idx >= 0:
                            have_stored_data = check_missing(crs, f, run_idx)
                            run_cnt += 1
                            update_db(exp_db, crs)
                        run_idx = create_runtable(crs, f)
                        have_stored_data = parse_filename(fname, parsers, run_idx, crs)
                    else:
                        # dummy values
                        run_idx = 1
                        dataset_idx = 0
                        parse_filename(fname, parsers, run_idx, crs)
                else:
                    if not dry_run:
                        if run_idx >= 0:
                            have_stored_data = check_missing(crs, data_filenames, run_idx)
                            run_cnt += 1
                            update_db(exp_db, crs)
                        run_idx = create_runtable(crs, data_filenames)
                        for f in data_filenames:
                            have_stored_data = parse_filename(f, parsers, run_idx, crs)
                    else:
                        # dummy values
                        run_idx = 1
                        dataset_idx = 0
                        for f in data_filenames:
                            parse_filename(f, parsers, run_idx, crs)
                
                if n_data_sources > 1:
                    create_new_table = False

            # Reset the parse nodes when going from one file to the next in "--sequential"
            # mode. This makes sense if you think of undefined/corrupted file endings. If
            # parsed data should be carried over from one file to another, "--join" should
            # be specified instead.
            if (seq_input and f_idx > 0):
                for p in parsers[data_inp_desc[fname]].nodes:
                    while not p.new_run():
                        # can only occur with "only_once" values (counters)
                        store_datavalue(p, crs, run_idx)

            # Make sure that all fixed values are stored in the experiment. Without this expplicit check,
            # this might not be the case if an input file is empty (no line parsed => no fixed value
            # triggered, parsed and stored).
            for p in parsers[data_inp_desc[fname]].nodes:
                if isinstance(p, fixed_value) and not p.new_run():
                    store_datavalue(p, crs, run_idx)

            # Now, the content of the file is parsed.
            parse_next_file = False
            for l_idx in range(line_idx[fname], line_cnt[fname] + 1):
                line_idx[fname] += 1
                if pb_debug:
                    print "*# Processing line:"
                    print "   ", rstrip(get_dataline(fname, l_idx))
                if l_idx % 10000 == 0 and pb_verbose:
                    t1 = time.clock()
                    print " at line %d (%d lines/s)" % (l_idx, 10000/(t1-t0))
                    t0 = t1

                for pn in parsers[data_inp_desc[fname]].nodes:
                    if isinstance(pn, (filename_location, derived_parameter)):
                        continue
                    if pn in removed_pn:
                        continue
                    
                    action = pn.check_trigger(fname, l_idx)
                    if action == "remove":
                        removed_pn[pn] = True
                        continue
                    if action == "abort":
                        raise DataError, "aborted by parsing element '%s'" % pn.name
                    if action == "new_run":
                        last_parsecnt.clear()
                        parse_cnt = 0
                        for p in parsers[data_inp_desc[fname]].nodes:
                            parse_cnt += p.get_parse_count()
                        if parse_cnt > 0:
                            if n_data_sources == 1 or seq_input:
                                for p in parsers[data_inp_desc[fname]].nodes:
                                    while not p.new_run():
                                        # can only occur with "only_once" values (counters)
                                        store_datavalue(p, crs, run_idx)
                                if not dry_run:
                                    if not check_missing(crs, data_filenames[f_idx:f_idx+1], run_idx):
                                        # this run is incomplete - abort parsing!
                                        stop_parsing = True
                                        break
                                    else:
                                        have_stored_data = True
                                        run_cnt += 1
                                        update_db(exp_db, crs)
                                    run_idx = create_runtable(crs, data_filenames)
                                    have_stored_data = parse_filename(fname, parsers, run_idx, crs)
                                else:
                                    if not check_missing(crs, data_filenames[f_idx:f_idx+1], run_idx):
                                        # this run is incomplete - abort parsing!
                                        stop_parsing = True
                                        break
                                    # dummy values:
                                    run_cnt += 1
                                    run_idx += 1
                                    dataset_idx = 0
                                    parse_filename(fname, parsers, run_idx, crs)
                            else:
                                # Need to process the other data files up to this point
                                # to store their data in the same runtable.
                                parse_next_file = True
                                create_new_table = True
                                break                            
                        # For the new run, all parse nodes are activated again.
                        removed_pn = {}
                        action = "parse"

                    if action == "parse":
                        try:
                            action = pn.parse_data(fname, l_idx)
                            if action == "store_set":
                                # Hook for the derived parameters
                                for dp in derived_params:                                    
                                    dp_action = dp.check_trigger(None, None)
                                    if dp_action == "parse":
                                        dp_action = dp.parse_data(None, None)
                                        if dp_action == "store_value":
                                            store_datavalue(dp, crs, run_idx)
                                if n_data_sources == 1 or seq_input: 
                                    store_dataset(parsers[data_inp_desc[fname]].nodes, crs, run_idx)
                                    have_stored_data = True
                                else:
                                    # Check if it makes sense to parse other files before trying to store
                                    # this dataset. This is the case if other files have lines to be
                                    # checked. To make sure that this dataset is stored even if the other
                                    # input files don't contribute, decrement the line counter. This will
                                    # lead us to this location again.
                                    # But if this is the last file to be checked, the dataset shold be
                                    # complete by now!
                                    if f_idx < len(data_filenames) - 1:
                                        for other_fname in data_filenames:
                                            if other_fname == fname:
                                                continue
                                            if line_idx[other_fname] <= line_cnt[other_fname]:
                                                # continue processing the other files
                                                parse_next_file = True
                                                line_idx[fname] -= 1
                                                break
                                        if parse_next_file:
                                            break

                                    merge_and_store_dataset(parsers, crs, run_idx)
                                    have_stored_data = True
                            elif action == "store_value":
                                # Hook for the derived parameters                            
                                for dp in derived_params:
                                    dp_action = dp.check_trigger(None, None)
                                    if dp_action == "parse":
                                        dp_action = dp.parse_data(None, None)
                                        if dp_action == "store_value":
                                            store_datavalue(dp, crs, run_idx)
                                store_datavalue(pn, crs, run_idx)
                                have_stored_data = True
                            elif action == "new_run":
                                # Only 'set_separator' may return 'new_run' when parsing.
                                parse_cnt = 0
                                last_parsecnt.clear()
                                for p in parsers[data_inp_desc[fname]].nodes:
                                    parse_cnt += p.get_parse_count()
                                if parse_cnt > 0:
                                    if n_data_sources == 1 or seq_input:
                                        for p in parsers[data_inp_desc[fname]].nodes:
                                            while not p.new_run():
                                                # can only occur with "only_once" values (counters)
                                                store_datavalue(p, crs, run_idx)
                                        if not dry_run:
                                            if not check_missing(crs, data_filenames[f_idx:f_idx+1], run_idx):
                                                # this run is incomplete - abort parsing!
                                                stop_parsing = True
                                                break
                                            else:
                                                have_stored_data = True
                                                run_cnt += 1
                                                update_db(exp_db, crs)
                                            run_idx = create_runtable(crs, data_filenames)
                                            have_stored_data = parse_filename(fname, parsers, run_idx, crs)
                                        else:
                                            if not check_missing(crs, data_filenames[f_idx:f_idx+1], run_idx):
                                                # this run is incomplete - abort parsing!
                                                stop_parsing = True
                                                break
                                            # dummy values:
                                            run_cnt += 1
                                            run_idx += 1
                                            dataset_idx = 0
                                            parse_filename(fname, parsers, run_idx, crs)
                                        removed_pn = {}
                                    else:
                                        # Need to process the other data files up to this point
                                        # to store their data in the same runtable.
                                        create_new_table = True
                                        parse_next_file= True
                                        break
                        except DataError, error_msg:
                            print "#* ERROR while parsing data file %s" % (fname, )
                            print "   ", error_msg
                            exit(1)
                if parse_next_file or stop_parsing:
                    # stop parsing this file, and proceed to the next file
                    break
                # end of lines-in-file loop 'for l_idx ...'
            if stop_parsing:
                # stop all parsing (emergency exit)
                break
            # end of file-from-filelest loop 'for f_idx ...'

        # Need to make sure that all data files have been parsed completely!
        for fname in data_filenames:
            if line_idx[fname] <= line_cnt[fname]:
                parse_next_file = True
        # end of loop 'while parse_next_file'

    if stop_parsing:
        have_store_data = False
    else:
        # Only check for missing data if we have not yet stored a complete run.
        # Relevant when parsing multiple runs from a single input file.
        if run_cnt == 0:
            if n_data_sources == 1:
                have_stored_data = check_missing(crs, data_filenames[f_idx:f_idx+1], run_idx)
            else:
                have_stored_data = check_missing(crs, data_filenames, run_idx)
    
    if have_stored_data:
        update_db(exp_db, crs)
        crs.close()
    else:
        raise DataError, "no data could be stored"
    
    return


def update_db(db, crs):
    # update 'modified' timestamps
    timestamp = mk_timestamp()       
    sqlexe(crs, "UPDATE exp_metadata SET last_modified = %s", None, (timestamp, ))
    
    # No data is stored before this transaction is terminated!
    db.commit()
    return


def hash_datafiles(filenames, crs):
    """Ensure that the specified datafiles can be used as input file.
    Check if they are accessible, and then calculate a hash value on the
    datafiles to verify that a given datafile has not already been stored
    in this experiment. Importing a datafile twice would
    distort the statistics generated from the data."""
    global input_hashes, join_input, line_cnt
    
    for fname in filenames:        
        if pb_profiling:
            t0 = time.clock()
        l_idx = 1

        if fname == '-':
            # Data from stdin can not be hashed - but it typically is original
            # data anyway!
            input_hashes[fname] = 0
            continue        
        if join_input:
            fname = pb_vfilename
        if pb_verbose:
            print "#* hashing file %s" % fname
        t0 = time.clock()
        
        # We need to speed up the hash generation: creating one single string from
        # the lines in the file is *veeeery* slow. We need to calculate a hash for
        # each line and relate these hashes to each other.
        try:
            l = get_dataline(fname, l_idx)
        except IndexError:
            input_hashes[fname] = 0
            line_cnt[fname] = 0
            if pb_verbose:
                print "#* file %s is empty" % (fname)
            continue

        hash_val = hash(l)
        data_len = len(l)
        max_hash = 2**33 - 1
        while True:
            l_idx += 1
            if l_idx % 10000 == 0 and pb_verbose:
                t1 = time.clock()
                print " at line %d (%d lines/s)" % (l_idx, 10000/(t1-t0))
                t0 = t1
            try:
                l = get_dataline(fname, l_idx)
            except IndexError:
                # EOF
                l_idx -= 1
                break 
            hash_val = ((100003*hash_val) ^ hash(l)) & max_hash
            data_len = data_len + len(l)
        input_hashes[fname] = (hash_val ^ data_len) & max_hash
        line_cnt[fname] = l_idx
        if pb_verbose:
            print "#* file %s has %d lines" % (fname, line_cnt[fname])

        sqlexe(crs, "SELECT index FROM run_metadata WHERE %d=ANY(input_hash) AND active" % long(str(input_hashes[fname])))
        run_idx = ""
        if crs.rowcount > 0 and not enforce_file[fname]:
            for db_row in crs.fetchall():
                run_idx += " %d" % db_row[0]
            if not join_input:
                raise DataError, "data file '%s': already processed (run index%s). No data imported." \
                      % (basename(fname), run_idx)
            else:
                dfiles = ""
                for v in filenames:
                    dfiles = dfiles + v + ','
                dfiles = dfiles[:-1]
                raise DataError, "The joint data files '%s' have already been processed (run index%s). No data imported." \
                      % (dfiles, run_idx)

        if pb_profiling:
            t0 = time.clock() - t0
            print "* profiling: hashing file %s took %f sec" % (fname, t0)

        if join_input:
            break

    return


def read_datafiles(filenames):
    """Read all file data into a list (one for each file) and return a dictionary of
    lists indexed by the filename."""
    global join_input, cache_sz, line_cnt

    total_sz = 0
    try:
         # we require that all files fit completely in memory
        for fname in filenames:
            if pb_profiling:
                t0 = time.clock()

            f = fname
            if join_input:
                f = pb_vfilename

            if fname != '-':
                # check if file is accessible
                data_fd = open(fname, 'r')
                data_fd.close()
                total_sz += os.stat(fname).st_size
                if total_sz > cache_sz and not join_input:
                    # access this file via the linecache module
                    if pb_debug:
                        print "#* processing file %s via linecache" % fname
                    continue
                
                # read file into memory completely now
                if pb_debug:
                    print "#* caching file %s in memory" % fname
                data_fd = open(fname, 'r')
                if not f in data_lines:
                    data_lines[f] = []
                data_lines[f].extend(data_fd.readlines())
                data_fd.close()                
            else:
                if not f in data_lines:
                    data_lines[f] = []
                data_lines[f].extend(sys.stdin.readlines())
                line_cnt[f] = len(data_lines[f])

            if pb_profiling:
                t0 = time.clock() - t0
                print "* profiling: reading file %s took %f sec" % (f, t0)
    except IOError, error_msg:
        print "#* ERROR: can not access input file '%s':" % f
        print "  ", error_msg
        exit(1)

    return


def get_valid_values(crs):
    """Build a dictionary indexed by value names. If a key exists, it returns
    a list of valid content for this value."""
    global parsers, valid_values
    
    for parser in parsers.itervalues():
        for node in parser.nodes:
            if node.get_value_names(): # some parse nodes may return "None"!
                for v_name in node.get_value_names():
                    valid_values[v_name] = None

    for v_name in valid_values.iterkeys():
        sqlexe(crs, "SELECT valid_values FROM exp_values WHERE name = %s", None, (v_name, ))
        nim = build_name_idx_map(crs)
        db_row = crs.fetchone()
        if db_row[0] != None:
            # create list of valid values from string of format {..,..,..}
            valid_values[v_name] = db_row[nim['valid_values']]
            for i in range(len(valid_values[v_name])):
                # for blank-separated entries, '"' are added which we don't want!
                valid_values[v_name][i] = valid_values[v_name][i].strip('"')
            
    return 


def create_pset(crs, pset_name):
    """Create (or update) a new parameter set in the current experiment. Failure to
    create is considered fatal. """
    # Check if pset does already exist - however, user needs admin rights to update
    # an existing pset!
    sqlexe(crs, "SELECT * FROM param_sets WHERE set_name = '%s'" % store_pset)
    if crs.rowcount > 0:
        return

    # Create a new one. All input-users can do this.
    try:
        sqlexe(crs, "INSERT INTO param_sets (set_name) VALUES ('%s')" % store_pset)
    except psycopg.ProgrammingError, error_msg:
        print "#* ERROR: can not create parameter set '%s'" % store_pset
        print "   ", error_msg
        sys_exit(1)
    return


def get_pset(crs, pset_name):
    """Get the content of a parameter set and return it in a dictionary. Failure to
    read the parameter set will return None."""
    sqlexe(crs, "SELECT * FROM param_sets WHERE set_name = '%s'" % pset_name)
    if crs.rowcount == 0:
        return None

    nim = build_name_idx_map(crs)
    row = crs.fetchone()
    pset = {}
    for n in nim.iterkeys():
        if n == "set_name":
            continue
        if row[nim[n]] is not None:
            pset[n] = row[nim[n]]
    
    return pset


def store_in_pset(crs, pset_name, p_name, p_content):
    """Set/update a parameter in a parameter set with the given content."""
    sqlexe(crs, "UPDATE param_sets SET %s = '%s' WHERE set_name = '%s'" % (p_name, p_content, pset_name),
           "DEBUG: updating pset:")
    return


def main(argv=None):    
    global data_filenames, all_exp_values, inp_descs, join_input
    global exp_db, exp_crs
    
    seed()
    
    if argv is None:
        argv = sys.argv[1:]   
    parse_cmdline(argv)

    if pb_profiling:
        t0 = time.clock()
        
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        parsers = parse_input_specs()
    else:
        try:
            parsers = parse_input_specs()
        except SpecificationError, error_msg:
            print "#* ERROR: can not process input descriptions" 
            print "   ", error_msg
            exit(1)
        # XXX Is there no better XML parse exception to catch!?
        except xml.parsers.expat.ExpatError, error_msg:
            print "#* ERROR: XML parse error in one of the input descriptions"
            print "  ", error_msg
            exit(1)
        except sre_constants.error, error_msg:
            print "#* ERROR: can not process input descriptions" 
            print "   ", error_msg
            exit(1)
        
    # If a parameter set is to be stored, we create the according line here.
    if store_pset is not None:
        create_pset(exp_crs, store_pset)

    get_valid_values(exp_crs)

    # build a dictionary of all values in the experiment
    sqlexe(exp_crs, "SELECT name from exp_values")
    for row in exp_crs.fetchall():
        if row[0] not in all_exp_values:
            # Only init the keys that have not been set before!
            all_exp_values[row[0]] = False

    read_datafiles(data_filenames)    
    if run_mode == "debug":
        hash_datafiles(data_filenames, exp_crs)
    else:
        try:
            hash_datafiles(data_filenames, exp_crs)
        except DataError, error_msg:
            print "#* ERROR: %s" % error_msg
            exit(1)

    if join_input:
        # use only one "virtual" input file". This does only work when using a
        # single input description.
        if len(inp_descs) != 1:
            raise SpecificationError, "option --join may only be used with a single input description"
        data_inp_desc[pb_vfilename] = data_inp_desc[data_filenames[0]]
        
        data_filenames = []
        data_filenames.append(pb_vfilename)
        
    if run_mode == "debug":
        parse_datafiles(data_filenames, parsers, exp_crs)
    else:
        try:
            parse_datafiles(data_filenames, parsers, exp_crs)
        except DataError, error_msg:
            print "#* ERROR: %s" % error_msg
            exp_db.rollback()
            exp_crs.close()
            exp_db.close()
            exit(1)
        except KeyboardInterrupt:
            print ""
            print "#* User aborted input operation. No data written to database."
            exp_db.rollback()
            exp_crs.close()
            exp_db.close()
            exit(0)
        #except DatabaseError, error_msg:
        #    print "#* ERROR: %s" % error_msg
        #    exit(1)

    if pb_profiling:
        print "* profiling information: total execution time %6.3f s" % (time.clock() - t0)
        for p in parsers.itervalues():
            for n in p.nodes:
                n.print_profiling()

    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print ""
            print "#* User aborted input operation. No data written to database."
        except DataError, error_msg:
            print "#* Could not store any data."
            print " ", error_msg
            exit(1)
        except SpecificationError, error_msg:
            print "#* Could not perform input operation."
            print " ", error_msg
            exit(1)
        except DatabaseError, error_msg:
            print "#* Could not store any data."
            print " ", error_msg
            exit(1)
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], inp_exp)
            else:
                print "#*", error_msg
            exit(1)
        except psycopg.Error, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], inp_exp)
            elif error_msg.args[0].find('does not exist') > 0:
                print "#* ERROR: The experiment '%s' does not exist on the database server %s:%d" \
                      % (inp_exp, db_info['host'], db_info['port'])
            else:
                print "#*", error_msg
            exit(1)
        except StandardError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            exit(1)
    exit(0)

