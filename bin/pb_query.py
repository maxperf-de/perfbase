# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#            (c) 2006 Joachim Worringen <joachim@maxperf.de>
#
# pb_query - Retrieve original and derived data from an experiment
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
from pb_query_classes import *
from pb_source import *
from pb_operators import *
from pb_outputs import *
from pb_plotutil import gnuplot

import sys
import re
import getopt
import xml
import time
import tempfile
from sys import exit, argv
from os import F_OK, R_OK, getenv, access, getpid
from string import find, split, rfind, whitespace, lower, upper, strip, rstrip
from xml.etree import ElementTree

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg

# global variables
qry_desc = None   # tuple (name, src) of the XML query description (src is "xml" or "db")
qry_exp = None        # name of the experiment
exp_db = None         # experiment database
all_nodes = {}        # all nodes in the query, indexed by their id
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None } 
fixed_values = {}  # cmd-line definition of constant values
pb_debug = False
sweep_alias = {}   # map an elements id to a list of all sweep-variants of this element (if any)

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase query - Retrieve (filtered and processed) data from an experiment"
    print "Arguments:"
    print "--desc=<file>, -d <file>    XML query description is stored in <file> ('-' for stdin)"
    print "--name=<name>, -n <name>    Use query description <name> from experiment database"
    print "--exp=<exp>, -e <exp>       Retrieve data from experiment <exp>"
    print "--run=<run_id>, -r <run_id> Retrieve data from run with the ID <run_id>"
    print "--fixed=<v=c> -f v=c        Set a value 'v' of to content 'c'"
    print_generic_dbargs()


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global qry_desc, qry_exp, pb_debug
    global fixed_values
    global db_info

    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)

    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVvd:n:e:r:f:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                                 'help', 'version', 'desc=', 'name=', 'exp=',
                                                                 'run=', 'fixed=', 'verbose', 'debug', 'profile',
                                                                 'sqltrace'])    
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        sys.exit(1)

    for o, v in options:
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
            sys.exit()
            continue
        if o in ("--version", "-V"):
            print_version()
            sys.exit()
            continue

        if o in ("-d", "--desc"):
            if qry_desc is None:
                qry_desc = (v, "xml")
            else:
                raise SpecificationError, "either use '--desc' or '--name' to specify query description!"
            continue
        if o in ("-n", "--name"):
            if qry_desc is None:
                qry_desc = (v, "db")
            else:
                raise SpecificationError, "either use '--desc' or '--name' to specify query description!"
            continue
        if o in ("-e", "--exp"):
            qry_exp = v
            continue
        if o in ("-r", "--run"):
            qry_run = v
            continue
        if o in ("-f", "--fixed"):
            all_vals = split(v, ',')
            for single_val in all_vals:
                fval = split(single_val, '=')
                if len(fval) != 2:
                    raise SpecificationError, "invalid argument %s to %s option" % (v, o)
                fixed_values[fval[0]] = fval[1]
            continue

        if o == "--dbhost":
            db_info['host'] = v
            continue
        if o == "--dbport":
            db_info['port'] = int(v)
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    pb_debug = do_debug()
    if pb_debug:
        print "#* DEBUG: cmdline is", argv2    
        print "#* DEBUG: using query description ", qry_desc
        print "#* DEBUG: fixed values are", fixed_values
        
    if not qry_desc:
        raise SpecificationError, "no query description specified (option '--name' or '--desc')"
    return


class query_node:
    def __init__(self, xml_node):
        self.id = xml_node.get("id")
        if not self.id:
            self.id = str(hash(xml_node))
            
        self.xml = xml_node
        self.initialized = False
        
        self.childs = [] # list of ids of child-nodes
        for n in xml_node.findall('input'):
            self.childs.append(n.text)
        return


def init_run(xml_node):
    global exp_db, all_nodes
    
    o = run(xml_node, exp_db, all_nodes)
    all_nodes[o.get_name()] = o

    return 


def init_series(xml_node):
    global exp_db, all_nodes
    
    o = series(xml_node)
    all_nodes[o.get_name()] = o

    return 


def init_fixed(xml_node):
    global exp_db, all_nodes, fixed_values

    f = fixed(xml_node)
    if f.get_name() in fixed_values:
        if be_verbose():
            print "#* fixed value '%s = %s' from command line overrides XML definition '%s'" % \
                  (f.get_name(), fixed_values[f.get_name()], f.get_content())
        return 

    all_nodes[f.get_name()] = f
    return 


def init_parameter(xml_node):
    global exp_db, all_nodes, sweep_alias

    sweep_nodes = xml_node.findall('sweep')
    if len(sweep_nodes) == 0:
        p = parameter(xml_node, exp_db, all_nodes)
        all_nodes[p.get_name()] = p
    else:
        filter_nodes = []
        if len(sweep_nodes) > 1:
            raise SpecificationError, "only a single <sweep> per <parameter> is allowed"
        for s_n in sweep_nodes:
            filter_nodes = s_n.findall('filter')
        idx = 0
        sweep_list = []
        if len(filter_nodes) == 0:
            # Create one sweep for every content of this parameter value. This is
            # a little hacky as we need to determine *here* which the different
            # content of this parameter, and create appropiate filters from it.
            p_name = xml_node.findtext('value')
            if not p_name:
                raise SpecificationError, "exactly one <value> per <parameter> is required!"
            for c in get_all_content(exp_db, p_name):
                f = ElementTree.Element("filter")
                eq = ElementTree.SubElement(f, "equal")
                eq.text = str(c)
                filter_nodes.append(f)
        for f in filter_nodes:
            p = parameter(xml_node, exp_db, all_nodes, f, idx)
            all_nodes[p.get_name()] = p
            idx += 1
            sweep_list.append(p.get_name())
        if len(filter_nodes) == 0:
            raise DataError, "no data available to perform a 'blind <sweep>'"            

        base_name = (p.get_name().split(pb_sweep_suffix))[0]
        sweep_alias[base_name] = sweep_list

    return


def init_source(xml_node):
    global exp_db, all_nodes, sweep_alias

    # Check for possible sweep-parameters , and build a specific map
    # of user-specified parameter names -> sweep parametet names
    # Sweep-results are treated differently as they produce objects which
    # are not "compatible".
    param_sweeps = {}
    param_map_list = None
    for p_n in xml_node.findall('input'):
        if len(p_n.text) > 0 and sweep_alias.has_key(p_n.text):
            # sweep parameter!
            param_sweeps[p_n.text] = sweep_alias[p_n.text]
    if len(param_sweeps) > 0:
        param_map_list = build_param_mapping(param_sweeps, False)
        
    if param_map_list:
        sweep_list = []
        for p in param_map_list:
            s = source(xml_node, all_nodes, exp_db, p)
            s_name = s.get_name()
            all_nodes[s_name] = s            
            sweep_list.append(s_name)
        sweep_alias[base_id(s_name)] = sweep_list
    else:
        s = source(xml_node, all_nodes, exp_db)
        all_nodes[s.get_name()] = s

    return


def process_input_sweep(xml_node):
    """Check for possible sweep-inputs, and build a specific map
    of user-specified input names -> sweep input names."""
    alltoall_sweeps = {}
    match_sweeps = {}
    input_map_list = None
    # different element types have different sweep resolve mode for "auto" setting
    sweep_mode_map = { "operator" : "extern", "combiner" : "intern", "output" : "intern" }
    
    sweep_combine = get_attribute(xml_node, "<%s>" % xml_node.tag, "sweep_combine", "match",
                                  ["match", "alltoall"])

    for i_n in xml_node.findall('input'):
        inp_name = i_n.text
        if sweep_alias.has_key(inp_name):
            sweep_mode = get_attribute(i_n, "<%s>" % xml_node.tag, "sweep_resolve", "auto",
                                       ["intern", "extern", "auto"])
            if sweep_mode == "auto":
                sweep_mode = sweep_mode_map[xml_node.tag]
            if sweep_mode == "intern":
                # Handle all sweeps of this <input> as separate <input> objects for the same object,
                # thus "absorbing" the sweeped variants internally.
                for sweep_inp_name in sweep_alias[inp_name]:
                    # Don't forget possible other attributes of the original input element.
                    sweep_inp = ElementTree.SubElement(xml_node, "input")
                    for k in i_n.keys():
                        if k == "sweep_resolve" or k == "sweep_combine":
                            continue
                        sweep_inp.set(k, i_n.get(k))
                    sweep_inp.text = sweep_inp_name
                xml_node.remove(i_n)
            elif sweep_mode == "extern":
                # Handle sweeped <input> by creating a new <operator/combiner/output> element for each <input>,
                # thus making the sweep externally visible.
                if sweep_combine == "match":
                    match_sweeps[inp_name] = sweep_alias[inp_name]
                else:
                    alltoall_sweeps[inp_name] = sweep_alias[inp_name]

    if len(alltoall_sweeps) > 0:
        input_map_list = build_param_mapping(alltoall_sweeps, False)                
    if len(match_sweeps) > 0:
        input_map_list = build_param_mapping(match_sweeps, True)

    return input_map_list
    

def init_operator(xml_node):
    global exp_db, all_nodes, sweep_alias

    input_map_list = process_input_sweep(xml_node)

    # We need to know the type of the operator *here* to instantiate the
    # related operator class!
    op_type = xml_node.get('type')
    if not op_type:
        op_type = "null"
    op_type = lower(op_type)
    if not pb_map_optype_opclass.has_key(op_type):
        raise SpecificationError, "<operator>: invalid 'type' attribute '%s'" % (op_type)
    op_class = pb_map_optype_opclass[op_type]

    if input_map_list:
        sweep_list = []
        for i in input_map_list:
            o = eval(op_class+"_operator")(xml_node, all_nodes, exp_db, i)
            o_name = o.get_name()
            all_nodes[o_name] = o
            sweep_list.append(o_name)
        sweep_alias[base_id(o_name)] = sweep_list
    else:
        # no sweeping
        o = eval(op_class+"_operator")(xml_node, all_nodes, exp_db)
        all_nodes[o.get_name()] = o

    return


def init_combiner(xml_node):
    global exp_db, all_nodes, sweep_alias

    sweep_group = xml_node.get('sweep_group')
    input_map_list = process_input_sweep(xml_node)
    
    # Now create the matching combiner(s)
    if input_map_list:
        sweep_list = []
        current_regexp = None
        while len(input_map_list) > 0:
            i = input_map_list[0]
            
            # We pass the input object's ID as a regular expression - this allows
            # to eventually pass a sweep_grooup specification in the same way as
            # a fixed input object ID.
            sweep_regexps = {}
            if sweep_group:
                for k, v in i.iteritems():
                    # Skip subsequent parameters of the sweep group that match the first one (the only
                    # one actually used).
                    if current_regexp is None or current_regexp.search(v) is None:
                        # Replace the numeric index after the parameter specified as sweep_group
                        # with a wild card to match *all* variants of this parameter.
                        v_parts = v.split(pb_sweep_suffix)
                        regexpstr_v = v_parts[0] + pb_sweep_suffix
                        skip_next = False
                        for idx in range(1,len(v_parts)):
                            if skip_next:
                                skip_next = False
                                continue
                            
                            if v_parts[idx] != sweep_group:
                                regexpstr_v += ".*" + pb_sweep_suffix
                            else:
                                regexpstr_v += v_parts[idx] + pb_sweep_suffix + v_parts[idx+1] + pb_sweep_suffix
                                # don't look at the next substring which is just the numerical
                                # index of thie sweep parameter
                                skip_next = True

                        regexpstr_v = regexpstr_v[:-1]
                        sweep_regexps[k] = re.compile(regexpstr_v)
                        current_regexp = sweep_regexps[k]

                        # remove all other sweep-configuration that belong to this group - this element covers
                        # them all!
                        rem_list = []
                        for i2 in input_map_list:
                            rem_dict = []
                            for k2, v2 in i2.iteritems():
                                if current_regexp.search(v2):
                                    rem_dict.append(k2)
                            for k2 in rem_dict:
                                del i2[k2]
                            if len(i2) == 0:
                                rem_list.append(i2)
                        for i2 in rem_list:
                            input_map_list.remove(i2)

                        break
            else:
                for k,v in i.iteritems():
                    sweep_regexps[k] = re.compile(v)
                input_map_list.remove(i)

            if len(sweep_regexps) == 0:
                continue
            c = combiner(xml_node, all_nodes, exp_db, sweep_regexps)
            c_name = c.get_name()
            all_nodes[c_name] = c
            sweep_list.append(c_name)        
        sweep_alias[base_id(c_name)] = sweep_list
    else:
        # no sweeping
        c = combiner(xml_node, all_nodes, exp_db)
        all_nodes[c.get_name()] = c
    
    return


def init_output(xml_node):
    global exp_db, all_nodes, sweep_alias

    target_type = xml_node.get('target')
    if not target_type:
        target_type = "raw_text"
    if not pb_valid_targets.has_key(target_type):
        raise SpecificationError, "invalid output target '%s'" % target_type
    elif not pb_valid_targets[target_type]:
        raise SpecificationError, "output target '%s' not yet supported" % target_type

    input_map_list = process_input_sweep(xml_node)

    # Now create the matching output(s)
    if input_map_list:
        sweep_list = []
        output_id = xml_node.get("id")
        if output_id is None:
            output_id = str(hash(xml_node))        
        for i in input_map_list:
            # each output objects needs a unique id
            new_id = output_id
            for sweep_name in i.itervalues():
                new_id += '_'+sweep_name[sweep_name.find(pb_sweep_suffix):]
            xml_node.set("id", new_id)

            o = eval(target_type+"_output")(xml_node, all_nodes, exp_db, i)

            o_name = o.get_name()
            all_nodes[o_name] = o
            sweep_list.append(o_name)                        
        sweep_alias[base_id(o_name)] = sweep_list
    else:
        # no sweeping
        o = eval(target_type+"_output")(xml_node, all_nodes, exp_db)
        all_nodes[o.get_name()] = o
    
    return


def init_query_objects(obj_id, qryobj_dag):
    global all_nodes
    
    idx = 0
    try:
        obj = qryobj_dag[obj_id]
    except KeyError:
        raise SpecificationError, "query object with id '%s' is not defined." % obj_id

    if obj.initialized:
        return 
    
    while len(obj.childs) > idx:
        init_query_objects(obj.childs[idx], qryobj_dag)
        idx += 1

    eval("init_"+obj.xml.tag)(obj.xml)
    obj.initialized = True
    
    return 


def parse_query_spec():
    """Parse the XML query specification and generate the appropiate data processing classes."""
    global qry_desc, qry_exp
    global db_info, exp_db, all_nodes, fixed_values, pb_all_ids
    global pb_map_optype_opclass
    global pb_sweep_suffix
    
    if be_verbose():
        print "#* Parsing query description from ", qry_desc

    # The query specification can be supplied in different ways, with this priority:
    # 1. --desc option on the command line (read from file)
    # 2. --name option on the commandl line (read from database)
    # 3. no options (read default query description from database) [NOT YET IMPLEMENTED]
    if qry_desc[1] == "xml":        
        if qry_desc[0] != '-':
            if access(qry_desc[0], F_OK|R_OK) == False:
                raise SpecificationError, "can not access query description %s" % qry_desc[0]
            qry_desc_file = qry_desc[0]
        else:
            qry_desc_file = sys.stdin 
    if qry_desc[1] == "db":
        if not qry_exp:
            # We need to know the experiment name already at this point!
            qry_exp = getenv("PB_EXPERIMENT")
            if not qry_exp:
                raise SpecificationError, "experiment name is not specified (option '--exp')"

        db_info['name'] = get_dbname(qry_exp)
        get_dbserver(None, db_info)

        exp_db = open_db(db_info, exp_name=qry_exp)
        if not exp_db:
            sys.exit(1)        
        if not check_db_version(exp_db, qry_exp):
            raise DatabaseError, "version mismatch of experiment database and commandline tools"
        crs = exp_db.cursor()

        if get_attachment_type(crs, qry_desc[0]) != "query":
            raise SpecificationError, "attachment '%s' is not a query description." % (qry_desc[0])

        qry_desc_fd = tempfile.NamedTemporaryFile(mode='w', prefix='pb_')
        if not dump_attachment(crs, qry_desc[0], qry_desc_fd):
            raise DataError, "could not dump attachment '%s' to temporary file '%s'" % (qry_desc[0], tmp_file.name)
        crs.close()
        qry_desc_file = qry_desc_fd.name

    qry_desc_tree = ElementTree.parse(qry_desc_file)
    qry_desc_root = qry_desc_tree.getroot()
    if qry_desc_root.tag != "query":
        raise SpecificationError, "%s is not a perfbase query description." % (qry_desc[0])
        
    # Determine the experiment and database and make sure it can be accessed.
    if not qry_exp:
        if qry_desc_root:
            # Try to retrieve experiment name from XML description
            qry_exp = qry_desc_root.findtext('experiment')
        if not qry_exp:
            # Last resort: use default experiment from environment
            qry_exp = getenv("PB_EXPERIMENT")
            if not qry_exp:
                raise SpecificationError, "experiment name is not specified (use option '--help' for help)"

    # Open the experiment database
    # Determine the database server to be used. Preference of the parameters:
    # cmdline > xml_file > environment > default
    if not exp_db:
        db_info['name'] = get_dbname(qry_exp)
        get_dbserver(qry_desc_tree, db_info)

        exp_db = open_db(db_info, exp_name=qry_exp)
        if not exp_db:
            sys.exit(1)
        if not check_db_version(exp_db, qry_exp):
            raise DatabaseError, "version mismatch of experiment database and commandline tools"

    # First, init the fixed values provided via the command line,
    # then look for non-initialized query objects and init them (see below)
    for k, v in fixed_values.iteritems():
        f = fixed(None, k, v)
        all_nodes[f.get_name()] = f        

    # Build an inventory of all available nodes, and their types, in pb_all_ids. Additionally,
    # build a directed acyclic graph of the whole query.
    obj_cnt = { "output":0, "source":0 }
    qryobj_dag = {}
    output_objs = []
    for obj_type in pb_query_objects:
        nodes = qry_desc_root.findall(obj_type)
        for n in nodes:
            node_id = n.get("id")

            if node_id:
                if pb_all_ids.has_key(node_id):
                    raise SpecificationError, "<%s> '%s': id is not unique" % (obj_type, node_id)
                pb_all_ids[node_id] = obj_type
            elif obj_type != "output":
                raise SpecificationError, "<%s> has no id attribute" % (obj_type)

            # build the object graph
            qryobj = query_node(n)
            qryobj_dag[qryobj.id] = qryobj

            if obj_type in obj_cnt:
                obj_cnt[obj_type] += 1
            if obj_type == "fixed":
                # The <fixed> objects need to be initialized before any other objects are,
                # and they are not really part of the tree - therefore, init them here.
                init_query_objects(qryobj.id, qryobj_dag)
            if obj_type == "output":
                output_objs.append(qryobj.id)

    for obj_type in ("source", "output"):
        if obj_cnt[obj_type] == 0:
            raise SpecificationError, "no data %s (element type <%s>) specified" % (obj_type, obj_type)    

    # Init all query objects from the graph via a depth-first search
    for obj_id in output_objs:
        init_query_objects(obj_id, qryobj_dag)

    # We need to gather all output objects. We can do this only after the init because
    # for certain sweeps, new output objects may be created. First, we add the defined
    # outputs in the order in which they apeared in the XML file.
    output_nodes = []
    for o in output_objs:
        try:
            output_nodes.append(all_nodes[o])
        except KeyError:
            # This can happen if an output object is "sweeped" away. It's instances will then
            # be added in the next loop.
            pass
    # It is possible that new output objects are generated (when a sweep is resolved externally
    # within an output object). Add these to the list.
    for o in all_nodes.itervalues():
        if o.type == "output" and o not in output_nodes:
            output_nodes.append(o)
    return output_nodes


def build_seqkey_sqllist(open_str, sep_str, close_str, content):
    "Build a string representation of a sequence."
    str_lst = open_str
    for c in content:
        str_lst += c + sep_str
    str_lst = rstrip(str_lst, sep_str) +  close_str
    
    return str_lst
    

def build_dictval_sqllist(open_str, sep_str, close_str, content):
    "Build a string representation of a sequence."
    str_lst = open_str
    for c in content:
        str_lst += content[c] + sep_str
    str_lst = rstrip(str_lst, sep_str) +  close_str
    
    return str_lst
      

def main(argvect=None):
    global exp_db
    
    create_query_table.idx = 0
    
    if argvect is None:
        argvect = argv[1:]   
    parse_cmdline(argvect)
    if do_profiling():
        t0 = time.clock()

    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        data_outputs = parse_query_spec()
    else:
        try:
            data_outputs = parse_query_spec()
        except SpecificationError, error_msg:
            print "#* ERROR: can not process query specification" 
            print "   ", error_msg
            sys.exit(1)
        except DatabaseError, error_msg:
            print "#* ERROR:", error_msg
            sys.exit(1)
        except DataError, error_msg:
            print "#* ERROR:", error_msg
            sys.exit(1)
        except xml.parsers.expat.ExpatError, error_msg:
            print "#* ERROR:", error_msg
            sys.exit(1)
                
    for d in data_outputs:
        if run_mode == "debug":
            d.perform_query(exp_db)
            d.store_data(exp_db)
        else:
            try:
                d.perform_query(exp_db)
                d.store_data(exp_db)
            except DataError, error_msg:
                print "#* ERROR:", error_msg
                sys.exit(1)
            except DatabaseError, error_msg:
                print "#* ERROR:", error_msg
                sys.exit(1)
            except SpecificationError, error_msg:
                print "#* ERROR:", error_msg
                sys.exit(1)

    for d in data_outputs:
        d.shutdown(exp_db)
    exp_db.close()

    if do_profiling():
        print "* profiling information: total execution time %6.3f s" % (time.clock() - t0)
        for n in all_nodes.itervalues():
            n.print_profiling()

    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except SpecificationError, error_msg:
            print "#* Could not perform query operation."
            print " ", error_msg
            sys.exit(1)
        except KeyboardInterrupt:
            print ""
            print "#* User aborted query operation."
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], qry_exp)
            else:
                print "#*", error_msg
            sys.exit(1)
        except DatabaseError, error_msg:
            print "#* Could not access any data."
            print " ", error_msg
            sys.exit(1)
        except StandardError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            sys.exit(1)
        
    sys.exit(0)
