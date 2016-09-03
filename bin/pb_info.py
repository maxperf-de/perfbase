# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_info - Retrieve information on perfbase experiments
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

from os import F_OK, R_OK, getenv, access, popen
from os.path import basename, dirname
from datetime import datetime
from string import lower
import getopt
import sys

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg

# global variables
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None } 
exp_name = None
runid = None
psetid = None
xmlid = None
all_exp = False
show_data = None
valid_data_keys = ("all", "multiple", "once")
show_inv = False
sort_key = "name"
valid_sort_keys = ("name", "creator", "created")
creator = None
list_deleted=False
user_filter = {}
values=[]

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase info - Print information on a perfbase experiment"
    print "Synopsis:"
    print "  perfbase info --all|[--exp=<exp> [--run=<runid>]] [--verbose]"
    print "Arguments:"
    print "--all, -a                   Give information on all available experiments"
    print "--exp=<exp>, -e <exp>       Give information on experiment <exp>"
    print "--inventory, -i             Print inventory of runs (id's of all active runs)"
    print "--run=<runid>, -r <runid>   Give information on run <runid> of experiment <exp>"
    print "--pset=<pid>, -p <pid>      Show content of parameter set <pid> of experiment <exp>"
    print "--value=<name>              Show info on all values with names matching <name> (may be regexp)"
    print "--xml=<xmlid>, -x <xmlid>   Show content of stored XML file <xmlid> of experiment <exp>"
    print "--sort=<key>, -s <key>      Sort experiment listing by <key>. Valid <key>s:"
    print "                             'name' (default)"
    print "                             'creator'"
    print "                             'created'"
    print "--data=<key>, -d <key>      When printing information on a run, also print the run's data"
    print "                            according to the content of the <key>: 'all', 'once', 'multiple'"
    print "--deleted                   List only the deleted runs."
    print "The following experiment listing filters may be combined as an 'or'-filter:"
    print "--creator=<name>            Only list experiments of creator 'name'"
    print "--admin=<user>              Only list experiments for which 'user' has admin access"
    print "--input=<user>              Only list experiments for which 'user' has input access"
    print "--query=<user>              Only list experiments for which 'user' has query access"
    print "--any=<user>                Only list experiments for which 'user' has any access at all"
    print ""
    print_generic_dbargs()


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global exp_name, runid, all_exp, show_inv, psetid, xmlid, values
    global sort_key, creator, show_data, list_deleted
    global db_info, user_filter
  
    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)

    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVve:r:ais:p:d:x:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                                     'help', 'version', 'verbose', 'exp=', 'run=',
                                                                     'all', 'inventory', 'sort=', 'creator=', 'data=',
                                                                     'admin=', 'input=', 'query=', 'any=', 'pset=',
                                                                     'xml=', 'value=', 'sqltrace', 'deleted'])
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
        if o == "--sqltrace":
            set_sql_trace(True)
            continue

        if o in ("-e", "--exp"):
            if not exp_name:
                exp_name = v
            else:
                print "#* ERROR: specifiy either --exp or --all"
                sys.exit(1)
            continue
        if o in ("-r", "--run"):
            runid = v
            try:
                all_digits = int(runid)
            except ValueError:
                print "#* ERROR: invalid run ID '%s' - has to be an integer value" % runid
                sys.exit(1)                
            continue
        if o in ("-p", "--pset"):
            psetid = v
            continue
        if o in ("-x", "--xml"):
            xmlid = v
            continue
        if o in ("-a", "--all"):
            if not exp_name:
                all_exp = True
            else:
                print "#* ERROR: specifiy either --exp or --all"
                sys.exit(1)
            continue
        if o in ("-i", "--inventory"):
            show_inv = True
            continue
        if o == "--deleted":
            list_deleted = True
            continue
        if o in ("-s", "--sort"):
            sort_key = v
            if not sort_key in valid_sort_keys:
                print "#* ERROR: invalid sort key '%s'" % sort_key
                sys.exit(1)                
            continue
        if o in ("-d", "--data"):
            show_data = v
            if not show_data in valid_data_keys:
                print "#* ERROR: invalid data key '%s'" % show_data
                sys.exit(1)
            continue
        if o == "--value":
            values.extend(v.split(','))
            continue
        if o == "--creator":
            creator = v
            continue
        if o == "--admin":
            user_filter["admin"] = v
            continue
        if o == "--input":
            user_filter["input"] = v
            continue
        if o == "--query":
            user_filter["query"] = v
            continue
        if o == "--any":
            user_filter["any"] = v
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

    if not exp_name and not all_exp:
        exp_name = getenv("PB_EXPERIMENT")
        if not exp_name:
            print "#* ERROR: no experiment specified. Use option '--help' for help."
            sys.exit(1)
    return


def show_db_info(pb_dbs):
    """Briefly list all available experiments"""
    global db_info
    global sort_key, creator, user_filter

    if pb_dbs is None:
        if be_verbose():
            print "#* Database server %s:%d does not contain any perfbase experiments." % \
                  (db_info['host'], db_info['port'])
        return

    all_dbs = []
    db_idx = []
    idx = 0
    for db in pb_dbs.itervalues():
        list_this_exp = False
        crs = db.cursor()
        sqlexe(crs, "SELECT * FROM exp_metadata")
        if idx == 0:
            meta_nim = build_name_idx_map(crs)
        db_row = crs.fetchone()
        if creator is None or creator == db_row[meta_nim['creator']]:
            list_this_exp = True
        db_version = 0
        if meta_nim.has_key('version') and not db_row[meta_nim['version']] is None:
            db_version = db_row[meta_nim['version']]

        if db_version >= 2 and len(user_filter) > 0:
            list_this_exp = False
            for acc in ['admin_access', 'input_access', 'query_access' ]:
                sqlexe(crs, "SELECT name FROM exp_access WHERE acc_type = '%s'" % acc)
                for k,v in user_filter.iteritems():
                    if (k == "any" or k == acc.rstrip("_access")) and crs.rowcount > 0:
                        for acc_row in crs.fetchall():
                            if acc_row[0] == v:
                                list_this_exp = True

        if list_this_exp:
            all_dbs.append(db_row)
            db_idx.append((db_row[meta_nim[sort_key]], idx))
            idx += 1
        crs.close()

    db_idx.sort()
    for i in range(idx):
        if be_verbose():
            print "%s" % all_dbs[db_idx[i][1]][meta_nim['name']]
            print "    Creator : %s (%s)" % \
                  (all_dbs[db_idx[i][1]][meta_nim['creator']], all_dbs[db_idx[i][1]][meta_nim['organization']])
            print "    Created :", all_dbs[db_idx[i][1]][meta_nim['created']]
            print "    Synopsis:", all_dbs[db_idx[i][1]][meta_nim['synopsis']]
        else:
            print "%-20s: %s" % (all_dbs[db_idx[i][1]][meta_nim['name']],
                                      all_dbs[db_idx[i][1]][meta_nim['synopsis']])
    return


def print_value_info(row, nim):
    """Print details on a parameter."""
    if be_verbose():
        # all you want to know about a value
        print " '%s': %s [%s]" % (row[nim['name']], row[nim['data_type']], row[nim['data_unit']])
        if row[nim['is_result']]:
            if row[nim['only_once']]:
                print "    result value, single occurence"
            else:
                print "    result value, multiple occurence"
        else:
            if row[nim['only_once']]:
                print "    parameter value, single occurence"
            else:
                print "    parameter value, multiple occurence"

        if row[nim['valid_values']] != None:
            print "    Valid values:", row[nim['valid_values']]
        if len(row[nim['synopsis']]) > 0:
            print "    Synopsis:", row[nim['synopsis']]
        if len(row[nim['description']]) > 0:
            print "    Description:", row[nim['description']]
        v_dflt = row[nim['default_content']]
        if v_dflt is not None:
            if len(v_dflt) > 0:
                print "    Default:", v_dflt
            else:
                print "    Default: NULL content"
    else:
        # everything in one line
        unit = "[%s]" % row[nim['data_unit']]
        if row[nim['default_content']] is not None:
            dflt = "D"
        else:
            dflt = " "
        if row[nim['only_once']]:
            occ = "O"
        else:
            occ = "M"
        if row[nim['is_result']]:
            vtype = "R"
        else:
            vtype = "P"

        print " %-20s :\t %-12s %-15s\t%s%s%s\t (%s)" % (row[nim['name']], row[nim['data_type']],
                                                     unit, vtype, occ, dflt, row[nim['synopsis']])

    return
    

def show_value_info(pb_dbs):
    """Print information on one or more values."""
    global exp_name, values

    # there's exactly one entry in pb_dbs!
    for db in pb_dbs.itervalues():
        pass
    
    crs = db.cursor()
    names_sql = ""
    for v in values:
        names_sql += " name~'%s' OR" % v
    names_sql = names_sql[:-2]
    
    sqlexe(crs, "SELECT * FROM exp_values WHERE %s ORDER BY name ASC" % names_sql)
    nim = build_name_idx_map(crs)
    db_row = crs.fetchone()
    while db_row:
        print_value_info(db_row, nim)
        db_row = crs.fetchone()    
    crs.close()
    
    return


def show_exp_info(pb_dbs):
    """Print experiment meta information."""
    global exp_name, show_inv

    # there's exactly one entry in pb_dbs!
    for db in pb_dbs.itervalues():
        pass
    
    crs = db.cursor()
    sqlexe(crs, "SELECT * FROM exp_metadata")
    if crs.rowcount == 0:
        print "#* ERROR: Corrupted database (missing experiment meta data)."
        return
    elif crs.rowcount > 1:
        print "#* ERROR: Corrupted database (multiple experiment meta data)."
        return
    nim = build_name_idx_map(crs)
    db_row = crs.fetchone()

    db_version = 0
    if nim.has_key('version') and not db_row[nim['version']] is None:
        db_version = db_row[nim['version']]
    if db_version != pb_db_version:
        print "#* WARNING: experiment '%s' has database version '%d' while perfbase commands have version '%d'" \
              % (exp_name, db_version, pb_db_version)
        if db_version > pb_db_version:
            print "            You should use a more recent version of the perfbase commands."
        else:
            print "            Update the experiment to current version using 'perfbase check --exp=%s --update'" % exp_name
        print ""

    print "Experiment %s (db_version %d)" % (db_row[nim['name']], db_version)
    print " Creator     :", db_row[nim['creator']]
    if be_verbose():
        print " Created     :", db_row[nim['created']]
        print " Modified    :", db_row[nim['last_modified']]
    if len(db_row[nim['organization']]) > 0:
        print " Organization:", db_row[nim['organization']]
    if len(db_row[nim['project']]) > 0:
        print " Project     :", db_row[nim['project']]
    print " Synopsis    :", db_row[nim['synopsis']]
    if len(db_row[nim['description']]) > 0:
        print " Description :", db_row[nim['description']]

    if be_verbose():
        print " Users   :"
        if db_version >= 2:
            for acc in ['admin_access', 'input_access', 'query_access' ]:
                sqlexe(crs, "SELECT * FROM exp_access WHERE acc_type = '%s'" % acc)
                if crs.rowcount > 0:
                    nim = build_name_idx_map(crs)
                    print "   %s:" % acc,
                    first_name = True
                    for db_row in crs.fetchall():
                        if not first_name:
                            print ",",
                        first_name = False
                        print db_row[nim['name']],
                        if db_row[nim['is_group']]:
                            print "(G)",
                    print " "
        else:
            print "   This experiment does not support multi-user access right managment."
            print "   It should be updated using 'perfbase check --update'"        
    
    # Don't list values here (option --val= can better be used for this purpose)
    if False:
        # Print information on values
        value_header = [ "Parameter values (single content per run):",
                         "Parameter values (multiple content per run):",
                         "Result values (single content per run):",
                         "Result values (multiple content per run):" ]
        value_sql    = [ "is_result = 'f' AND only_once = 't'",
                         "is_result = 'f' AND only_once = 'f'",
                         "is_result = 't' AND only_once = 't'",
                         "is_result = 't' AND only_once = 'f'" ]
        n_param_vals = 0
        n_result_vals = 0

        for idx in range(4):
            if be_verbose():
                print ""
                print value_header[idx]
            sqlexe(crs, "SELECT * FROM exp_values WHERE %s ORDER BY name ASC" % value_sql[idx])
            nim = build_name_idx_map(crs)
            if be_verbose():
                db_row = crs.fetchone()
                while db_row:
                    print_value_info(db_row, nim)
                    db_row = crs.fetchone()
            else:
                if idx < 2:
                    n_param_vals += crs.rowcount
                else:
                    n_result_vals += crs.rowcount

        if not be_verbose():
            print " Values      : %d parameters" % n_param_vals
            print "               %d results" % n_result_vals
        print ""

    # Print information on parameter sets
    if be_verbose() and db_version > 2:
        sqlexe(crs, "SELECT set_name FROM param_sets")
        if crs.rowcount == 0:
            print "No parameter sets defined.",
        else:
            print "Available parameter sets:"
            psets = []
            db_row = crs.fetchone()
            while db_row:
                psets.append(db_row[0])
                db_row = crs.fetchone()
            psets.sort()
            for p in psets:
                print "  ", p
        print ""

    # Print information on attachments
    if be_verbose() and db_version > 3:
        for xml_type in ('input', 'query'):
            sqlexe(crs, "SELECT name FROM xml_files WHERE type = %s", None, (xml_type, ))
            if crs.rowcount == 0:
                print "No %s descriptions attached." % xml_type
            else:
                print "Attached %s descriptions:" % xml_type
                attch = []
                db_row = crs.fetchone()
                while db_row:
                    attch.append(db_row[0])
                    db_row = crs.fetchone()
                attch.sort()
                for a in attch:
                    print "  ", a
            print ""

    if be_verbose():
        print_run_info(pb_dbs)
        
    crs.close()
    return


# Print information on runs
def print_run_info(pb_dbs):
    """Print active and deleted runs."""
    global show_inv

    # there's exactly one entry in pb_dbs!
    for db in pb_dbs.itervalues():
        pass
    
    crs = db.cursor()

    cond = [ 't', 'f' ]
    desc = [ 'Active', 'Deleted' ]

    for idx in range(2):
        sqlexe(crs, "SELECT * FROM run_metadata WHERE (active = '%s')" % cond[idx])
        nim = build_name_idx_map(crs)

        print ""
        print " %s runs : %d"  % (desc[idx], crs.rowcount)

        if show_inv:
            run_idx = []
            db_row = crs.fetchone()
            while db_row:
                run_idx.append(db_row[nim['index']])
                db_row = crs.fetchone()
            run_idx.sort()
            print " Indices of %s runs:" % desc[idx].lower()
            print run_idx
        
    crs.close()
    return


def show_pset(pb_dbs):
    """Show content of a parameter set. """
    # there's exactly one entry in pb_dbs!
    for db in pb_dbs.itervalues():
        pass
    
    crs = db.cursor()

    sqlexe(crs, "SELECT * FROM param_sets WHERE set_name = '%s'" % psetid)
    if crs.rowcount == 0:
        print "#* ERROR: parameter set '%s' does not exist." % psetid
    else:
        pset_nim = build_name_idx_map(crs)
        pset_row = crs.fetchone()
        print "parameter set '%s':" % pset_row[pset_nim['set_name']]

        sqlexe(crs, "SELECT name FROM exp_values WHERE is_result = 'f' AND only_once = 't'")
        if crs.rowcount > 0:
            pname_rows = crs.fetchall()        
            for r in pname_rows:
                vn = r[0].lower()
                if pset_nim.has_key(vn):
                    cntnt = pset_row[pset_nim[vn]]
                    if cntnt is not None:
                        print "  %s = %s" % (r[0], str(cntnt))
                    
    crs.close()
    return


def show_xml(pb_dbs):
    """Show content of a stored xml file. """
    # there's exactly one entry in pb_dbs!
    for db in pb_dbs.itervalues():
        pass
    
    crs = db.cursor()

    if not dump_attachment(crs, xmlid, sys.stdout):
        print "#* Error: XML attachment '%s' does not exist." % xmlid
                          
    crs.close()
    return


def show_run_info(pb_dbs):
    """Print detailed information on a specific run"""
    global runid, show_data

    # there's exactly one entry in pb_dbs!
    for db in pb_dbs.itervalues():
        pass

    crs = db.cursor()
    sqlexe(crs, "SELECT * FROM run_metadata WHERE (index = %s)", None, (runid, ))
    if crs.rowcount == 0:
        print "#* ERROR: run %s does not exist." % runid
        return    
    db_row = crs.fetchone()
    nim = build_name_idx_map(crs)

    sqlexe(crs, "SELECT * FROM rundata_once WHERE run_index = %s" % runid)
    once_values = 0
    if crs.rowcount == 1:        
        once_row = crs.fetchone()
        for i in range(1, len(crs.description)):
            if once_row[i] != None:
                once_values += 1
    sqlexe(crs, "SELECT COUNT(*) FROM rundata WHERE pb_run_index=%s" % runid)
    tab_data_sets = crs.fetchone()[0]
    if tab_data_sets + once_values == 0:
        print " run %s does not contain any data." % runid
        return
    print "Run %s contains %d datasets and %d singular values." % (runid, tab_data_sets, once_values)
    print "  Creator:   %s" % db_row[nim['creator']]
    print "  Performed: %s" % db_row[nim['performed']]
    print "  Created:   %s" % db_row[nim['created']]
    if db_row[nim['active']]: print "  Active :   Yes"
    else: print "  Active :   No"
    print "  Datafiles:"
    for n in db_row[nim['input_name']]:
        print "   ", n
        #    for i in range(len(db_row[10])):
        #        print "%s [%s] %s" % (basename(db_row[10][i]), dirname(db_row[10][i]), db_row[11][i])
        #        if be_verbose:
        #            print "  Hash: %s" % hex(db_row[9][i])
    if len(db_row[nim['synopsis']]) > 0:
        print "  Synopsis: ", db_row[nim['synopsis']]
    if len(db_row[nim['description']]) > 0:
        print "  Description: ", db_row[nim['description']]
    if db_row[nim['data']]:
        print "  Source: ", db_row[nim['data']]

    if show_data == "all" or show_data == "multiple":
        sqlexe(crs, "SELECT * FROM rundata WHERE pb_run_index=%s" % runid)
        print "  Datasets: "
        print "    (",
        for d in crs.description:
            print "%s," % d[0],
        print ")"
        db_row = crs.fetchone()
        while db_row:
            print "   ", db_row
            db_row = crs.fetchone()
    if show_data == "all" or show_data == "once":
        print "  Per-run values: "
        sqlexe(crs, "SELECT * FROM rundata_once WHERE run_index = %s", None, (runid, ))
        db_row = crs.fetchone()
        if db_row:
            idx = 0
            for d in crs.description:
                print "    %s = %s" % (d[0], db_row[idx])
                idx += 1
        else:
            print "   #* No per-run values available."
       
    return


def main(argv=None):
    global all_exp, db_info, psetid, xmlid, runid, values
    
    if argv is None:
        argv = sys.argv[1:]   
    parse_cmdline(argv)

    # Determine the database server to be used. Preference of the parameters:
    # cmdline > environment > default
    get_dbserver(None, db_info)

    try:
        if all_exp:
            pb_dbs = find_all_experiments(db_info)
        else:
            pb_dbs = {}
            db_info['name'] = get_dbname(exp_name)
            # Open the experiment database
            if do_debug():
                print "#* Connecting to experiment database '%s' on '%s:%s' as '%s'" % \
                      (db_info['name'], db_info['host'], db_info['port'], db_info['user'])
            pb_dbs[db_info['name']] = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                                                       (db_info['host'], db_info['port'], db_info['user'],
                                                        db_info['name'], db_info['password']))            
    except psycopg.Error, error_msg:
        # This check is somewhat hacky - the error string could change. However, we
        # want to let the user know that no experiment is available at all (in which
        # case --all doesn't really help...).
        if error_msg.args[0].find('database "%s" does not exist' % db_info['name']) > 0:
            print "#* ERROR: experiment '%s' not found with database server on '%s:%d'. " \
                  % (exp_name, db_info['host'], db_info['port'])
            print "   Use option --all to list all available experiments."
        else:
            print "#* ERROR: could not access database server on host '%s:%d'." % (db_info['host'], db_info['port'])
            print "   error message: ", error_msg
        sys.exit(1)            

    try:
        if all_exp:
            show_db_info(pb_dbs)
        elif runid:
            show_run_info(pb_dbs)
        elif psetid:
            show_pset(pb_dbs)
        elif xmlid:
            show_xml(pb_dbs)
        elif len(values) > 0:
            show_value_info(pb_dbs)
        else:
            show_exp_info(pb_dbs)
    except KeyboardInterrupt:
        print ""
        print "#* User aborted operation."
    except psycopg.ProgrammingError, error_msg:
        if error_msg.args[0].find('permission denied') > 0:
            if exp_name != 'perfbase':
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], exp_name)
            else:
                print "#* ERROR: user '%s' has insufficient privileges to access perfbase database server" \
                      % (db_info['user'])
        else:
            print "#*", error_msg

    if pb_dbs is not None:
        for v in pb_dbs.itervalues():
            v.close()

    return


if __name__ == "__main__":
    main()
    sys.exit(0)
