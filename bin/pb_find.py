# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_find - Locate experiments or runs inside a perfbase server
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

import sys
import os
import getopt

from os import getenv
from string import split, lower
from xml.etree import ElementTree

from pb_common import *

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg

# global variables
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None } 
exp_name = None
search_desc = None
from_create = None
to_create = None
from_perform = None
to_perform = None
synopsis = None
sort_val = None
create_users = []
show_vals = []
show_meta = []
show_all = []
sort_val = None
is_multiple = {}
need_quotes = {}
nvals = 1
sql_cond_mult = ""

# valid filter relations
filter_rels = [ "<=", ">=", "!=", "=", "<", ">" ]
# filtering of values to be applied. This dictionary lists will contain tuples (value_name, content)
filter_vals = { }

valid_meta_keys = { 'syno':'synopsis', 'desc':'description', 'crtr':'creator',
                    'tspf':'performed', 'tsin':'created', 'indx':'index',
                    'file':'input_name', 'ninp':'nbr_inputs' }

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase find - Locate runs inside a perfbase experiment via a content search."
    print "Synopsis:"
    print "  perfbase find --desc=<xml>|--name=<name>|[...] [--verbose]"
    print "Arguments:"
    print "--desc=<xml>, -d <xml>      XML search description is stored in <xml>"
    print "--name=<name>, -n <name>    Use search description <name> from experiment database"
    print "--exp=<exp>, -e <exp>       Search for a run inside experiment <exp>."
    print "--created-from=<date>       Only return entries that were created not earlier than <date>"
    print "--created-to=<date>         Only return entries that were created not later than <date>"
    print "--performed-from=<date>     Only return entries that were performed not earlier than <date>"
    print "--performed-to=<date>       Only return entries that were performed not later than <date>"
    print "--created-by=<user>         Only return entries that were created by <user>"
    print "--synopsis=<s>              Only return entries that have a machting synopsis (regexp)"
    print "--cond=<name><op><content>, -c <name><op><content>"
    print "                            Only return entries where the variable <name> is in a"
    print "                            relation <op> (<, >, =, !=, <=, >=) to <content>"
    print "--show=<name>, -s <name>    For the listed runs, show the variable <name> (multiple)"
    print "--nvals=<n>                 Show up to 'n' distinct content elements per value"
    print "--meta=<label[,label,...]>, -m <label[,label,...]>"
    print "                            Specify meta information to be displayed for all runs."
    print "                             Valid labels are:"
    print "                             syno   synopsis"
    print "                             desc   description"
    print "                             crtr   creator of the run"
    print "                             tspf   timestamp when run was performed"
    print "                             tsin   timestamp when run data was imported"
    print "                             indx   run index"
    print "                             file   name of input file(s)"
    print "                             ninp   number of input file(s)"
    print "--sort=<col>                Sort by column <col> (parameter, result or meta)"
    print_generic_dbargs()


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global exp_name, create_users, from_create, to_create, from_perform, to_perform, search_desc, synopsis
    global show_vals, show_meta, show_all, sort_val, filter_rels, filter_vals, nvals
    global db_info, valid_meta_keys
  
    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)

    for f in filter_rels:
        filter_vals[f] = []

    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVvd:n:e:c:s:m:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                                   'help', 'version', 'verbose', 'debug', 'sqltrace',
                                                                   'desc=', 'exp=', 'name=', 'sort=', 'synopsis=',
                                                                   'created-from=', 'created-from=', 'created-by=',
                                                                   'performed-from=', 'performed-to=', 
                                                                   'cond=', 'show=', 'nvals=', 'meta=' ])
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        sys.exit(1)

    for o, v in options:
        if o in ("-v", "--verbose"):
            set_verbose(True)
            continue
        if o in ("-h", "--help"):
            print_help()
            sys.exit()
            continue
        if o in ("--version", "-V"):
            print_version()
            sys.exit()
            continue
        if o == "--debug":
            set_debug(True)
            continue
        if o == "--sqltrace":
            set_sql_trace(True)
            continue

        if o in ("-d", "--desc"):
            search_desc = v
            continue
        if o in ("-e", "--exp"):
            exp_name = v
            continue
        if o in ("-n", "--name"):
            search_name = v
            continue
        if o == "--nvals":
            try:
                nvals = int(v)
            except ValueError:
                print "#* ERROR: invalid argument '%s' to option '%s'" % (v, o)
                sys.exit(1)
            continue

        if o == "--created-from":
            from_create = v
            continue
        if o == "--created-to":
            to_create = v
            continue
        if o == "--performed-from":
            from_perform = v
            continue
        if o == "--performed-to":
            to_perform = v
            continue
        if o == "--created-by":
            create_users.extend(v.split(';'))
            continue
        if o == "--synopsis":
            synopsis = v
            continue
        if o == "--sort":
            sort_val = v
            continue

        if o in ("-s", "--show"):
            show_vals.extend(v.split(','))
            show_all.extend(v.split(','))
            continue
        if o in ("-m", "--meta"):
            for m in v.split(','):
                try:
                    show_meta.append(valid_meta_keys[m])
                    show_all.append(valid_meta_keys[m])
                except KeyError:
                    print "#* ERROR: invalid meta key '%s' " % m
                    sys.exit(1)                                    
            continue
        
        if o == "-c" or o == "--cond":
            for vv in v.split(','):
                valid = False
                for f in filter_rels:
                    vvv = vv.split(f)
                    if len(vvv) == 2:
                        filter_vals[f].append((vvv[0], vvv[1]))
                        valid = True
                        break
                if not valid:
                    print "#* ERROR: invalid argument '%s' to option '-c'" % vv
                    sys.exit(1)                
            continue

        if o == "--dbhost":
            db_info['host'] = v
            continue
        if o == "--dbport":
            db_info['port'] = v
            continue
        if o == "--dbname":
            exp_name = v
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    if len(show_meta) + len(show_vals) == 0:
        show_meta.append(valid_meta_keys['indx'])
        show_all.append(valid_meta_keys['indx'])

    if not exp_name:
        exp_name = getenv("PB_EXPERIMENT")
        if not exp_name:
            print "#* ERROR: no experiment specified"
            print_help()
            sys.exit(1)
    return


def parse_xml(xml_desc):
    global exp_name
    
    xml_tree = ElementTree.parse(xml_desc)
    xml_root = xml_tree.getroot()

    if xml_root.tag != "search":
        raise SpecificationError, "%s is not a perfbase search description." % (xml_desc)

    exp = xml_tree.findtext('experiment')
    if exp:
        if not exp_name:
            exp_name = exp

    # parse remaining elements...
    print "#* WARNING: XML parsing is not yet implemented."
    
    return


def filter_exp(crs):
    valid_runs = []
    sql_cond = "active"

    if len(create_users) > 0:
        sql_cond += " AND ("
    for u in create_users:
        sql_cond += " creator='%s' OR" % u
    if len(create_users) > 0:
        sql_cond = sql_cond[:-2] + ")"        
        
    if synopsis:
        sql_cond += " AND synopsis~'%s'" % synopsis

    if from_perform:
        sql_cond += " AND performed>='%s'" % from_perform
    if to_perform:
        sql_cond += " AND performed<='%s'" % to_perform

    if from_create:
        sql_cond += " AND created>='%s'" % from_create
    if to_create:
        sql_cond += " AND created<='%s'" % to_create

    sqlexe(crs, "SELECT index FROM run_metadata WHERE %s" % sql_cond, "#* DEBUG: gather valid runs (1):" )
    db_rows = crs.fetchall()
    if not db_rows:
        return valid_runs
    for r in db_rows:
        valid_runs.append(r[0])

    return valid_runs


def filter_runs(crs, runs):
    global filter_rels, filter_vals, sql_cond_mult
    global need_quotes, is_multiple
    
    valid_runs = []
    sql_cond_once = ""
    sql_cond_mult = ""
  
    # First, apply the filtering for the only-once values.
    for f in filter_rels:
        for l in filter_vals[f]:
            # XXX need to make boolean condition parametrizable
            if is_multiple[l[0]]:
                if need_quotes[l[0]]:
                    sql_cond_mult += "AND %s%s'%s' " % (l[0], f, l[1])
                else:
                    sql_cond_mult += "AND %s%s%s " % (l[0], f, l[1])
            else:
                if need_quotes[l[0]]:
                    sql_cond_once += "AND %s%s'%s' " % (l[0], f, l[1])
                else:
                    sql_cond_once += "AND %s%s%s " % (l[0], f, l[1])

    if len(sql_cond_mult) + len(sql_cond_once) == 0:
        return runs

    if len(sql_cond_once) > 0:
        sqlexe(crs, "SELECT run_index FROM rundata_once WHERE %s" % sql_cond_once[4:],
               "#* DEBUG: gather valid runs (2):" )
        db_rows = crs.fetchall()
        if db_rows:
            for r in db_rows:
                if r[0] in runs:
                    valid_runs.append(r[0])
    else:
        valid_runs.extend(runs)
    
    # Now, check the full data of each remaining run.
    remove_runs = []
    if len(sql_cond_mult) > 0:
        run_filter = "WHERE"
        if len(valid_runs) > 0:
            run_filter += " ("
            for run in valid_runs:
                run_filter += "pb_run_index=%d OR " % run
            run_filter = run_filter[:-3] + ') AND '

        sqlexe(crs, "SELECT DISTINCT pb_run_index FROM rundata %s (%s)" % (run_filter, sql_cond_mult[4:]),
               "#* DEBUG: gather valid runs (3):" )
        db_rows = crs.fetchall()
        if not db_rows:
            # No runs do not match.
            remove_runs.extend(valid_runs)
        else:
            matching_runs = []
            for r in db_rows:
                matching_runs.append(r[0])
            for r in valid_runs:
                if not r in matching_runs:
                    remove_runs.append(r)
        
    for run in remove_runs:
        valid_runs.remove(run)
        
    return valid_runs


def print_runs(crs, runs, show_vals):
    global need_quotes, is_multiple, nvals, sql_cond_mult, show_all, sort_val

    cond = ""
    if len(sql_cond_mult) > 0:
        cond = "%s" % sql_cond_mult[4:]

    if sort_val is not None:
        if sort_val in valid_meta_keys:
            sort_val = valid_meta_keys[sort_val]
        if sort_val not in show_all:
            show_all.append(sort_val)
        show_all.remove(sort_val)
        show_all.insert(0, sort_val)        
    else:
        sort_val = show_all[0]

    # need to create separate list with lower-case only entries 
    order_vals = []
    for v in show_all:
        order_vals.append(v.lower())

    runs.sort()
    all_lines=[]
    for r in runs:
        new_l = ["dummy"]
        idx_l = {}
        idx = 1
        
        qry_vals = ""
        for v in show_vals:
            if not is_multiple[v]:
                qry_vals += "%s," % v
        if len(qry_vals) > 0:
            sqlexe(crs, "SELECT %s FROM rundata_once WHERE run_index = %d" % (qry_vals[:-1], r))
            nim = build_name_idx_map(crs)
            row = crs.fetchone()
            for k in nim.iterkeys():
                if k == sort_val.lower():
                    new_l.pop(0)
                    new_l.insert(0, row[nim[k]])
                    idx_l[lower(k)] = 0
                else:
                    new_l.append(row[nim[k]])
                    idx_l[lower(k)] = idx
                    idx += 1

        qry_vals = ""
        for m in show_meta:
            qry_vals += "%s," % m
        if len(qry_vals) > 0:
            sqlexe(crs, "SELECT %s FROM run_metadata WHERE index = %d" % (qry_vals[:-1], r))
            nim = build_name_idx_map(crs)
            row = crs.fetchone()
            for k in nim.iterkeys():
                if k == sort_val.lower():
                    new_l.pop(0)
                    new_l.insert(0, row[nim[k]])
                    idx_l[lower(k)] = 0
                else:
                    new_l.append(row[nim[k]])
                    idx_l[lower(k)] = idx
                    idx += 1

        for v in show_vals:
            if is_multiple[v]:
                sql_qry = "SELECT DISTINCT %s FROM rundata WHERE pb_run_index=%d" % (v, r)
                if len(cond) > 0:
                    sql_qry += " AND (%s)" % cond
                sqlexe(crs, sql_qry)
                if crs.rowcount == 0:
                    text = "#no_data#"
                elif crs.rowcount <= nvals or nvals < 0:
                    text = ""
                    for d in crs.fetchall():
                        text += str(d[0])+'|'
                    text = text[:-1]
                else:
                    text = "#%dvalues#" % crs.rowcount
                    
                if v == sort_val.lower():
                    new_l.pop(0)
                    new_l.insert(0, text)
                    idx_l[lower(v)] = 0
                else:
                    new_l.append(text)
                    idx_l[lower(v)] = idx
                    idx += 1


        all_lines.append(new_l)

    if be_verbose():
        print_tab = False    
        print "#",
        for v in show_all:
            if print_tab:
                print "\t",
            print "%s" % v,
            if not print_tab:
                print_tab = True
        print

    all_lines.sort()
    for l in all_lines:
        print_tab = False    
        for v in order_vals:
            if print_tab:
                print "\t",
            if v in valid_meta_keys:
                v = valid_meta_keys[v]
            print "%s" % l[idx_l[v]],
            if not print_tab:
                print_tab = True
        print
        
    return


def main(argv=None):
    global is_multiple, need_quotes
    global db_info, exp_name, search_desc
    
    if argv is None:
        argv = sys.argv[1:]   
    parse_cmdline(argv)

    # Parse XML if necessary, either from an XML description within a file or within the experiment.
    if search_desc:
        parse_xml(search_desc)

    # Determine the database server to be used. Preference of the parameters:
    # cmdline > environment > default
    get_dbserver(None, db_info)
    db_info['name'] = get_dbname(exp_name)
    db = open_db(db_info, exp_name=exp_name)
    crs = db.cursor()  
    
    # Check if all specified values are actually contained in the experiment.
    all_vals = []
    for v in show_vals:
        all_vals.append(v)
    for f in filter_rels:
        for l in filter_vals[f]:
            all_vals.append(l[0])

    for v in all_vals:
        sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (v, ))
        nim = build_name_idx_map(crs)
        if crs.rowcount == 0:
            print "#* ERROR: value '%s' does not exist in the specified experiment '%s'." % (v, exp_name)
            sys.exit(1)
        if crs.rowcount == 1:
            db_row = crs.fetchone()
            is_multiple[v] = not db_row[nim['only_once']]
            if get_value_type(db_row, nim) in ("bool", "string", "version"):
                need_quotes[v] = True
            else:
                need_quotes[v] = False
            
    # Filter all runs of the experiment via the run-related conditions (created-by, -from, -to,
    # synopsis, description,)
    valid_runs = filter_exp(crs)

    # Filter the valid runs via run-related conditions (limits on individual values)
    valid_runs = filter_runs(crs, valid_runs)

    # Print the valid runs and the specfied values within these runs
    print_runs(crs, valid_runs, show_vals)

    crs.close()
    db.close()
    
    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], exp_name)
            else:
                print "#*", error_msg
            sys.exit(1)
        except KeyboardInterrupt:
            print "#* User aborted operation."
        except SpecificationError, error_msg:
            print "#* Invalid operation:"
            print "  ", error_msg
            sys.exit(1)
        except StandardError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            sys.exit(1)
    sys.exit(0)
