# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_common - collection of utility functions and common definitions
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

from xml.etree import ElementTree
from string import lower, find, count, split, rstrip, printable
from os import getenv, getpid
from socket import gethostname
from datetime import datetime
from time import localtime, strftime, sleep
from sys import exit

import math

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
#
# globals
#
pb_debug = False
pb_sql_trace = False
pb_verbose = False
pb_profiling = False

pb_all_ids = {}

#
# constants
#
pb_basedb = "template1"

pb_release_version = "0.9.5"
pb_release_date = "13th September 2006"
pb_db_version = 5
pb_db_comment = "perfbase experiment "

pb_namesrc_sep = '@'    # name-src separator for eval operator (only internal visibility)
pb_label_sep   = '###'  # seperates parameter elements in labels (only internal visibility)
pb_filter_str  = '???'  # specifies a filter string which is determined during the query, not before
pb_max_idx_cnt = 14     # maximum number of index marks on an axis in a plot

pb_valid_dtypes = {
    'integer':'integer',
    'integer(2)':'smallint',
    'integer(4)':'integer',
    'integer(8)':'bigint',
    'float':'float',
    'float(4)':'float',
    'float(8)':'double precision',
    'string':'varchar(256)',
    'text':'text',
    'date':'date',
    'timeofday':'time',
    'duration':'interval',
    'timestamp':'timestamp',
    'binary':'bytea',
    'boolean':'boolean',
    'version':'version_nbr'
    }

pb_valid_funcs = {
    'acos':1, 'acosh':1,
    'asin':1, 'asinh':1,
    'atan':1, 'atanh':1,
    'atan2':2,
    'ceil':1,
    'cos':1, 'cosh':1,
    'exp':1,
    'fabs':1,
    'abs':1,
    'floor':1,
    'fmod':1,
    'hypot':2,
    'ldexp':2,
    'log':1,
    'log10':1,
    'pow':2,
    'sin':1, 'sinh':2,
    'sqrt':1,
    'tan':1, 'tanh':1,
    'max':2,
    'min':2,
    'erfc':1
    }

pb_valid_baseunits = {
    'none':'number without a unit',
    '%':'arbitrary percentage (of utilization)',
    'ppm' : 'parts per million (1e-6)',
    'byte':'a byte (made up of 8 bits)',
    'bit':'single bit of information (0 or 1)',
    'flop':'floating point operation',
    'op':'(integer) operation',
    'process':'measure of parallelism',
    'event':'any kind of integral event',
    's':'the SI unit for time',
    'Hz':'frequency',
    'h':'hour',
    'd':'day',
    'a':'year',
    'm':'the SI unit for distance',
    'g':'the SI unit for mass (use scaling to get kg',
    'A':'the SI unit for current',
    'K':'the SI unit for temperature',
    'mol':'the SI unit for amount of a substance',
    'cd':'the SI unit for luminous intensity',
    '$':'US Dollar',
    'Y':'Japanese Yen',
    'EUR':'Euro'
    }

pb_scale_values = {
    'K':1e3,
    'M':1e6,
    'G':1e9,
    'T':1e12,
    'P':1e15,
    'm':1e-3,
    'u':1e-6,
    'n':1e-9,
    'p':1e-12,
    'f':1e-15,
    'Ki':1024,
    'Mi':1048576,
    'Gi':1073741824,
    'Ti':1099511627776L,
    'Pi':1125899906842624L
    }

pb_scale_values_reverse = {
    1:'',
    1e3:'K',
    1e6:'M',
    1e9:'G',
    1e12:'T',
    1e15:'P',
    1e-3:'m',
    1e-6:'u',
    1e-9:'n',
    1e-12:'p',
    1e-15:'f',
    1024:'Ki',
    1048576:'Mi',
    1073741824:'Gi',
    1099511627776L:'Ti',
    1125899906842624L:'Pi'
    }

pb_valid_scales = {
    'Kilo':'K',
    'Mega':'M',
    'Giga':'G',
    'Tera':'T',
    'Peta':'P',
    'milli':'m',
    'micro':'u',
    'nano':'n',
    'pico':'p',
    'femto':'f',
    'Ki':'Ki',
    'Mi':'Mi',
    'Gi':'Gi',
    'Ti':'Ti',
    'Pi':'Pi'
    }

pb_origin_colname   = "_pb_data_origin_"
pb_dataidx_colname  = "_pb_data_idx_"
pb_runidx_colname   = "_pb_run_idx_"
pb_runorder_colname = "_pb_run_order_"

pb_valid_targets  = { 'raw_binary':False, 'raw_text':True, 'netcdf':False, 'hdf5':False,
                      'gnuplot':True, 'grace':False, 'latex':False, 'xml':True, 'opendoc':True }
pb_sql_string_types = {'string':True, 'text':True, 'date':True, 'timeofday':True,
                       'duration':True, 'timestamp':True, 'version':True }
pb_query_objects = [ "output", "combiner", "operator", "source", "parameter", "run", "fixed", "series" ]

pb_sweep_suffix = '~'

pb_imap = { 'name':0,
            'vname':1,
            'pbtype':2,
            'sqltype':3,
            'unit':4,
            'syn':5,
            'filter':6
            }

pb_months = [ 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 
              'jul', 'aug', 'sep', 'oct', 'nov', 'dec' ]
#
# exceptions
#
# exceptions
class SpecificationError(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return `self.msg`
    
class DataError(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return `self.msg`
    
class DatabaseError(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return `self.msg`
    

#
# classes
#
# TODO: derive from threading.Thread in order to execute concurrently 
# with other instances.
class data:
    """This base class defines the interface of all other classes the process data from
    the database up to the data that is provided to the user."""
    def __init__(self, element_tree, query_nodes, db):
        """element_tree is the XML definition for the operator; query_nodes is 'None' for
        this class. db is the experiment database."""
        self.name = "data"
        self.synopsis = element_tree.findtext("synopsis")
        self.description = element_tree.findtext("description")
        self.type = "NONE"
        self.tgt_table = ""
        
        # profiling information: one list of durations for each function to be profiled. For now,
        # only these two function are really of interest.
        self.prof_data = { 'perform_query' : [], 'store_data' : [] }
        return
    def shutdown(self, db):
        """Clean up & shutdown"""
        return
    def get_name(self):
        """Provide the name of this instance."""
        return self.name
    def get_type(self):
        return self.type
    def perform_query(self, db):
        """Call all data elements to gather the data. Has to be called once; after this,
        call the get_*_info() functions to get to know the data that will be provided. With
        this information, the get_next_*() functions deliver the datasets until no more data
        is available."""
        return 
    def store_data(self, db, table_name = None):
        """Store the internally processed data in the output table."""
        return
    def remove_data(self, db):
        return
    def get_param_info(self):
        """Supply a list of lists for each parameter that this object provides per dataset
        (sorted by priorities). Structure of this tuple:
        [[0]: parameter SQL name, [1]: parameter verbose name, [2]: perfbase type, [3]: sql type,
        [4]: phys. unit, [5]: synopsis, [6]: filter]"""
        return None
    def get_next_paramset(self):
        """Return the next dataset as a dictionary, indexed by the names, mapped to the contents.
        The order of the provided datasets is determined by sorting."""
        return None
    def get_result_info(self):
        """Supply a list of lists for each result that this object provides per dataset
        (sorted by priorities). Structure of this tuple:
        (parameter SQL name, parameter verbose name, perfbase type, sql type, phys. unit, synopsis, filter)"""
        return None
    def get_table_name(self):
        """Return the name of the (temporary) SQL table in which this object will store its
         output data"""
        return self.tgt_table
    def update_filters():
        """This function is a little bit hacky, but necessary to update previously unspecified filters
        with conditions that are only available after a query has been performed. It returns a list
        of tuples witht two elements each: the first element is a substring to be replaced with the
        second element. An emptly list is returned if no update is necessary."""
        return []
    def get_next_resultset(self):
        """Return the result values as a dictionary, indexed by the names, mapped to lists of
        contents."""
        return None
    def print_profiling(self):
        """Print out the collected profiling data (number of calls, min/max/avg of processing time)."""

        print ""
        print "* profiling information for %s with id %s" % (self.type, self.name)

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
            
#
# generic support functions
#
def print_version():
    """Print version and copyright information."""
    global pb_release_version, pb_release_date, pb_db_version

    print "perfbase release %s (%s), database version %d" % (pb_release_version, pb_release_date, pb_db_version)
    print "(c) 2004-2006 C&C Research Labs, NEC Europe Ltd."
    print "perfbase comes with ABSOLUTELY NO WARRANTY; for details type `perfbase version -w'."
    print "This is free software, and you are welcome to redistribute it"
    print "under certain conditions; type `perfbase version -c' for details."



def print_generic_dbargs():
    """Print the generic command line arguments for all perfbase tools."""
    print "--dbhost=<host>             Connect to database server on <host> (default: localhost)"
    print "--dbport=<port>             Connect to <port> (default 5432)."
    print "--dbuser=<user>             Login to database as <user>"
    print "--dbpasswd=<pw>             Database password for <user>"
    print "--help, -h                  Print this help"
    print "--version, -V               Give version information"
    print "--verbose, -v               Be verbose"

def argv_preprocess(argv):
    """Transform the generic 'argv' into a pre-processed version to properly support
    quoted strings with spaces. This is important to formulate a synopsis or description
    parameter on the command line. Examples:
    A. The command line '-s \"first version of flux optimization\"' would be represented as
    a sequence with 6 strings: ['-s', '"first', 'version', 'of', 'flux', 'optimization"'].
    This will be transformed into ['-s', 'first version of flux optimization']
    B: 

    I: argvec    Sequence of all white-space separated individual strings from the command line
    O:           Sequence of strings in which substrings have been merged to a single string
                 according to quotes and escaped spaces.
                 """
    argv2 = []
    tmp_argv = []
    in_string = False
    for a in argv:
        if len(a) == 0:
            continue

        qpos = a.find('"')
        if qpos == -1 and not in_string:
            argv2.append(a)
            continue

        # remove quote from string
        while qpos >= 0:
            in_string = not in_string
            a = a[:qpos] + a[qpos+1:]
            qpos = a.find('"')
        tmp_argv.append(a)
        
        if not in_string:
            new_arg = ""
            while len(tmp_argv) > 0:
                new_arg += tmp_argv.pop(0) + ' '
            new_arg = new_arg[:-1]

            argv2.append(new_arg)

    if in_string:
        raise StandardError, "Invalid quoting on commandline: check for pairwise match of double quotes."
    return argv2
                 
def param_count(argv):
    cnt = 0
    for a in argv:
        if a[0] == '-':
            cnt += 1
    return cnt

def do_debug():
    global pb_debug
    return pb_debug

def set_debug(val):
    global pb_debug
    pb_debug = val
    return

def sql_trace():
    global pb_sql_trace
    return pb_sql_trace

def set_sql_trace(val):
    global pb_sql_trace
    pb_sql_trace = val
    return

def set_profiling(val):
    global pb_profiling
    pb_profiling = val
    return

def do_profiling():
    global pb_profiling
    return pb_profiling

def be_verbose():
    global pb_verbose
    return pb_verbose

def set_verbose(val):
    global pb_verbose
    pb_verbose = val
    return

def get_attribute(node, obj_name, att_name, default = None, valid = None):
    # Get an attribute from an XML element. Optionally check for validity and and provide a
    # default value if attribute is not specified.
    att = node.get(att_name)
    if att is not None:
        if valid is not None and not att in valid:            
            raise SpecificationError, "%s: invalid content '%s' of attribute '%s' (valid: %s)" % \
                  (obj_name, att, att_name, valid)
    elif default is not None:
        att = default
        
    return att

#
# support functions to determine database (server)
#

def get_dbserver(xml_root, db_info):
    """Determine the database server to be used. Preference of the parameters:
    cmdline > xml_file > environment > default """
    exp_db = None
    if xml_root:
        exp_db = xml_root.find('database')
    if db_info['host'] is None:
        if exp_db:
            db_info['host'] = exp_db.findtext('host')
        if db_info['host'] is None:
            db_info['host'] = getenv("PB_DBHOST")
        if db_info['host'] is None:
            db_info['host'] = "localhost"
    if db_info['port'] is None:
        p = -1
        if exp_db:
            p = exp_db.findtext('port')
        if p < 0:
            p = getenv("PB_DBPORT")
        if p < 0:
            # default port number of PostgreSQL's portmaster
            p = 5432
        db_info['port'] = int(p)
    if db_info['user'] is None:
        # This is wrong as there can be many "users" defined in the experiment description,
        # and these users are not necessarily related to the owner/creator of the database.
        #if exp_db:
        #    db_info['user'] = exp_db.findtext('user')
        if db_info['user'] is None:
            db_info['user'] = getenv("PB_DBUSER")
        if db_info['user'] is None:
            db_info['user'] = getenv("USER")        # under Unix, USER is typically set
        if db_info['user'] is None:
            db_info['user'] = getenv("USERNAME")    # under Window, USERNAME is set
        if db_info['user'] is None:
            print "#* ERROR: database user could not be determined!"
            sys.exit(1)
    if db_info['password'] is None:
        if exp_db:
            db_info['password'] = exp_db.findtext('passwd')
        if db_info['password'] is None:
            db_info['password'] = getenv("PB_DBPASSWD")
        if db_info['password'] is None:
            db_info['password'] = ""

    if pb_debug:
        print "#* perfbase database:", db_info

    return 


def check_db_version(db, exp_name=None):
    """Check if the version of the experiment database is compatible with the version
    of this release of the perfbase commands."""
    global pb_db_version

    rval = True
    
    crs = db.cursor()
    if not exp_name:
        # this table has exactly one row
        sqlexe(crs, "SELECT name FROM exp_metadata" )
        if crs.rowcount != 1:
            raise DatabaseError, "corrupted metadata table (experiment name not found)"
        exp_name = (crs.fetchone())[0]
    
    sqlexe(crs, "SELECT * FROM exp_metadata WHERE name='%s'" % exp_name)
    if crs.rowcount == 0:
        raise SpecificationError, "Experiment '%s': no metadata stored. "\
              "Check spelling of experiment name (uppercase/lowercase!)" \
              % exp_name
    if crs.rowcount > 1:
        raise SpecificationError, "corrupted experiment '%s': more than one set of metadata stored." % exp_name
    nim = build_name_idx_map(crs)

    db_version = 0
    if nim.has_key('version'):
        db_row = crs.fetchone()
        db_version = db_row[nim['version']]

    if db_version != pb_db_version:
        print "#* ERROR: experiment '%s' has database version '%d' while perfbase commands have version '%d'" \
              % (exp_name, db_version, pb_db_version)
        if db_version > pb_db_version:
            print "          You need to use a more recent version of the perfbase commands."
        else:
            print "          Update the experiment to current version using 'perfbase check --exp=%s --update'" % exp_name
        rval = False

    return rval


def find_all_experiments(db_info):
    """Using the pqsl tool or a direct connection to the template database, this function
    determine all perfbasee experiments available at the given database server. 
    Returns a dictionary that maps the database name to the database descriptor.
    Returns None if no perfbase experiments could be found."""
    global pb_db_comment

    pb_dbs = {}
    if False:
        # Use psql command - requires this command to be in the path. Suboptimal.
        try:
            psql = popen('psql -c "\l+" %s' % pb_basedb, 'r')
        except:
            print "#* ERROR: can not run pqsl. Make sure it is found in $PATH."
            sys.exit(1)

        psql_output = psql.readlines()
        psql.close()

        for line in psql_output:
            words = line.split()
            if (len(words) == 0):
                continue
            if words[0].find("pb_") == 0:
                pb_dbs[words[0]] = None
    else:
        if do_debug():
            print "#* Connecting to experiment database '%s' on '%s:%d' as '%s'" % \
                  (pb_basedb, db_info['host'], db_info['port'], db_info['user'])
        # Better: connect to template1 database and find all pb_* databases
        db = None
        db = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                              (db_info['host'], db_info['port'], db_info['user'],
                               pb_basedb, db_info['password']))
        crs = db.cursor()
        sqlexe(crs, "SELECT datname FROM pg_database WHERE datname~'^pb_'")
        for row in crs.fetchall():
            pb_dbs[row[0]] = None

        crs.close()
        db.close()

    for db_name in pb_dbs.iterkeys():        
        try:
            pb_dbs[db_name] = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                                               (db_info['host'], db_info['port'], db_info['user'],
                                                db_name, db_info['password']))
        except psycopg.Error, error_msg:
            # Inaccessable database
            pb_dbs[db_name] = None

        if pb_dbs[db_name] is not None:
            # Make sure it really is a perfbase experiment. This test is not bullet-proof,
            # but definetly makes some sense!
            is_pb_db = True
            have_access = True
            crs = pb_dbs[db_name].cursor()
            try:
                sqlexe(crs, "SELECT name FROM exp_metadata")
            except psycopg.ProgrammingError, error_msg:
                if error_msg.args[0].find('permission denied') > 0:
                    print "#* ERROR: user '%s' has insufficient privileges to access experiment database '%s'" \
                          % (db_info['user'], db_name)
                    have_access = False
                else:
                    print "#*", error_msg
                    is_pb_db = False
                
            if have_access and is_pb_db:
                if crs.rowcount == 1:
                    db_row = crs.fetchone()
                    if "pb_"+db_row[0].lower() != db_name:
                        # Consistency check failed!
                        is_pb_db = False
                else:
                    is_pb_db = False

            crs.close()
            if not have_access or not is_pb_db:
                pb_dbs[db_name].close()
                pb_dbs[db_name] = None
                if not is_pb_db:
                    print "#* WARNING: found corrupt perfbase experiment database '%s'" % db_name

    rval = {}
    for k, v in pb_dbs.iteritems():
        if v is not None:
            rval[k] = v

    if len(rval) == 0:
        rval = None
            
    return rval


#
# support functions for database interaction
#

def sqlexe(crs, cmd, msg=None, args=None):
    if sql_trace() or do_debug():
        if do_debug() and msg is not None:
            print msg
        if args is None:
            print "#* SQL:", cmd
        else:
            print "#* SQL:", cmd, args
    crs.execute(cmd, args)
    return

def get_attachment_type(crs, xml_name):
    sqlexe(crs, "SELECT type FROM xml_files WHERE name = %s", None, (xml_name, ))
    if crs.rowcount > 0:
        att_type = crs.fetchone()[0]
    else:
        # not found
        att_type = None
        
    return att_type


def dump_attachment(crs, xml_name, fd):
    sqlexe(crs, "SELECT xml FROM xml_files WHERE name = %s", None, (xml_name, ))
    if crs.rowcount > 0:
        fd.write(crs.fetchone()[0])
        fd.flush()
        return True
    else:
        return False


def get_dbname(exp_name):
    return lower("pb_" + exp_name)


def admin_db(db_info, sql_cmd):
    global pb_basedb

    try:
        base_db = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                                   (db_info['host'], db_info['port'], db_info['user'],
                                    pb_basedb, db_info['password']))
    except psycopg.Error, error_msg:        
        print "#* ERROR: can not connect to control database %s" % pb_basedb
        print "   ", error_msg
        return False
    # can not create database inside a transaction
    base_db.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    crs = base_db.cursor()
    
    try:
        sqlexe(crs, sql_cmd)
    except psycopg.Error, error_msg:
        print "#* ERROR: can not perform command with database %s" % db_info['name']
        print "   Command:", sql_cmd
        print "   Result:", error_msg
        return False
    crs.close()
    base_db.close()
    return True


def create_db(db_info, owner):
    "Create a new database."
    if owner is None:
        owner = db_info['user']
    sql_cmd = "CREATE DATABASE %s OWNER %s" %(db_info['name'], owner)
    return admin_db(db_info, sql_cmd)


def drop_db(db_info):
    """Drop the experiment database (used if XML error occurs on creation)."""
    sql_cmd = "DROP DATABASE %s" % db_info['name']
    # wait a second or two to make sure database is no longer "busy"
    sleep(2)
    return admin_db(db_info, sql_cmd)


def open_db(db_info, run_silently=False, exp_name=""):
    """Open a database on the (PostgreSQL) database server."""
    if do_debug():
        print "#* Connecting to database '%s' on '%s:%s'" % (db_info['name'], db_info['host'], db_info['port'])

    try:
        db = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                              (db_info['host'], db_info['port'], db_info['user'],
                               db_info['name'], db_info['password']))
    except psycopg.Error, error_msg:
        if not run_silently:
            # This check is somewhat hacky - the error string could change. However, we
            # want to let the user know that no experiment is available at all (in which
            # case --all doesn't really help...).
            if error_msg.args[0].find('database "%s" does not exist' % db_info['name']) > 0:
                print "#* ERROR: experiment '%s' not found with database server on '%s:%d'. " \
                      % (exp_name, db_info['host'], db_info['port'])
                print "   Use command 'perfbase info --all' to list all available experiments."
            elif error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], exp_name)
            else:
                print "#* ERROR: could not access database server on host '%s:%d'." % (db_info['host'], db_info['port'])
                print "   error message: ", error_msg
        db = None
    return db


def get_value_type(db_row, nim):
    """Determine if the value is a date, a number or a string."""
    type = "invalid"
    if db_row[nim['is_numeric']]:
        type = "number"
    elif db_row[nim['data_type']] == "boolean":
        type = "bool"
    elif db_row[nim['data_type']] == "binary":
        type = "binary"
    elif db_row[nim['data_type']][:6] == "string" or db_row[nim['data_type']] == "text":
        type = "string"
    elif db_row[nim['data_type']] == "version":
        type = "version"
    else:
        type = "date"
    return type


def quote_value(db_row, nim, val):
    if get_value_type(db_row, nim) in ("bool", "string", "version", "date"):
        return "'"+str(val)+"'"
    else:
        return str(val)


def get_quoted_value(vname, vtype):
    if vtype in ("bool", "string", "version", "date", "text"):
        return "'"+clean_string(vname)+"'"
    else:
        return vname


def mk_sql_const(sql_type, content):
    "Transform a content into a valid SQL constant (depending on the SQL type)"

    for st in ["varchar", "text" ]:
        if find(sql_type, st) != -1:
            return "'%s'" % content
    return content    


def create_query_table(db, columns):
    # We need to create a temporary table in which we gather data from
    # different run tables.  We then can perform SQL aggregat
    # operations on the data in this table. Need to find a unique
    # table name, though, which we construct using an internal counter.
    # This table will hold the complete data (no
    # differentation between constant and changing values). Also, no
    # default values and no constraints will be applied - data that
    # does not exist wil be NULL.   
    query_table = "qt_"+str(create_query_table.idx)

    crs = db.cursor()
    qrytable_str = "%s serial," % pb_dataidx_colname
    qrytable_str += "%s varchar(256)," % pb_origin_colname
    qrytable_str += "%s integer," % pb_runidx_colname
    qrytable_str += "%s integer," % pb_runorder_colname
    for c in columns:
        # Duplicate entries are caused by invalid query specification.
        if columns.count(c) > 1:
            raise SpecificationError, "duplicate entry of value '%s'" % c[0]
        qrytable_str += "%s %s," % c
    qrytable_str = rstrip(qrytable_str, ",")
    if pb_debug:
        print "#* DEBUG: creating temporary query table:"
        print "   ",qrytable_str

    sqlexe (crs, "CREATE TEMPORARY TABLE %s (%s)" % (query_table, qrytable_str))
    sqlexe (crs, "CREATE INDEX pb_dataidx_index_%d ON %s (%s)" % 
            (create_query_table.idx, query_table, pb_dataidx_colname))
    db.commit()
    crs.close()

    create_query_table.idx += 1
    return query_table


def drop_query_table(db, table_name):
    # As we use temporary tables, we don't need to drop them anymore!
    #
    #if pb_debug:
    #    print "#* DEBUG: dropping temporary query table %s" % table_name
    #crs = db.cursor()
    #crs.execute ("DROP TABLE %s" % table_name)
    #db.commit()
    #crs.close()
    return


def get_sql_contents(pv_info, value):
    if pb_sql_string_types.has_key(pv_info[2]):
        rval = "'" + clean_string(str(value)) +"'"
        return rval
    elif pv_info[2] == "boolean":
        if value:
            return "'t'"
        else:
            return "'f'"
    else:
        if value is not None:
            return str(value)
        else:
            return "NULL"


def clean_string(input_string):
    """Remove non-printable characters from strings. Such characters do cause confusion when
    inserted into SQL tables (the insertion will fail).
    Is there something faster than this?"""
    rval = ""
    for c in input_string:
        if c in printable:
            if c == "'":
                rval += "\\'"
            else:
                rval += c
    return rval


def build_name_idx_map(crs):
    """Return a dictionary that map the column name to its number in the row(s) of
    the cursor 'crs'."""
    name_idx_map = {}
    for i in range(len(crs.description)):
        name_idx_map[crs.description[i][0]] = i
    return name_idx_map


def table_access_rights(crs, name, is_group, table, action, acc_type):
    """Set access rights for a table. name can be a user, a group or PUBLIC."""
    grp = ' '
    if is_group:
        grp = ' GROUP '
    cmd_map = { 'REVOKE':' FROM ', 'GRANT':' TO' }
    sql_cmd = action+" "+acc_type+" ON "+table+cmd_map[action.upper()]+grp+name
    if do_debug():
        print "#* DEBUG: setting access rights to table:"
        print "   ",sql_cmd
    sqlexe(crs, sql_cmd)
    return
    

def fix_access_rights(crs, index, db_version=None):
    """Set the access rights of the tables in the database according to the content
    of the exp_access table.
    If  no specific table is given (index is None), fix the complete database. Otherwise,
    only set the access rights for the rundata table with the given index."""

    if db_version is None:
        sqlexe(crs, "SELECT version FROM exp_metadata")
        if crs.rowcount == 0:
            raise SpecificationError, "corrupted experiment: no metadata stored."
        if crs.rowcount > 1:
            raise SpecificationError, "corrupted experiment: more than one set of metadata stored."
        db_version = crs.fetchone()[0]
    
    try:
        run_tables = []
        all_tables = []
        if index is None:
            meta_tables = ['exp_metadata', 'run_metadata', 'exp_values', 'exp_access', 'rundata_once' ]
            if db_version > 2:
                meta_tables.append('param_sets')
            if db_version > 3:
                meta_tables.append('xml_files')
                
            all_tables.extend(meta_tables)

            sqlexe(crs, "SELECT index FROM run_metadata")
            for db_row in crs.fetchall():
                run_tables.append("rundata_"+str(db_row[0]))
        else:
            run_tables.append("rundata_"+str(index))
            meta_tables = []

        # Version 5 and above have all rundata in a single table.
        if db_version == 5:
            run_tables = ["rundata"]

        all_tables.extend(run_tables)            
        if len(meta_tables) > 0:
            for t in all_tables:
                table_access_rights(crs, 'PUBLIC', False, t, 'REVOKE', 'ALL')

        for acc in ['admin_access', 'input_access', 'query_access', 'no_access' ]:
            sqlexe(crs, "SELECT * FROM exp_access WHERE acc_type = '%s'" % acc)
            nim = build_name_idx_map(crs)
            for db_row in crs.fetchall():
                user = db_row[nim['name']]
                is_group = db_row[nim['is_group']]
                
                if acc == 'admin_access':
                    for t in all_tables:
                        table_access_rights(crs, user, is_group, t, 'GRANT', 'ALL')
                elif acc == 'input_access':
                    if len(meta_tables) > 0:
                        for t in meta_tables:
                            table_access_rights(crs, user, is_group, t, 'REVOKE', 'ALL')
                            
                        for t in meta_tables:
                            if t in ['exp_values',  'exp_access']:
                                table_access_rights(crs, user, is_group, t, 'GRANT', 'SELECT')
                            if t in ['exp_metadata']:
                                table_access_rights(crs, user, is_group, t, 'GRANT', 'SELECT, UPDATE')
                            if t in ['param_sets', 'rundata_once']:
                                table_access_rights(crs, user, is_group, t, 'GRANT', 'INSERT, UPDATE, SELECT')
                            if t in ['run_metadata']:
                                table_access_rights(crs, user, is_group, t, 'GRANT', 'INSERT, UPDATE, SELECT')
                                # XXX shouldn't ..._index_seq be transparent to us?
                                table_access_rights(crs, user, is_group, 'run_metadata_index_seq', \
                                                    'GRANT', 'INSERT, UPDATE, SELECT')
                            if t in ['xml_files']:
                                table_access_rights(crs, user, is_group, 'xml_files', 'GRANT', 'INSERT, UPDATE, SELECT')
                    for t in run_tables:
                        table_access_rights(crs, user, is_group, t, 'REVOKE', 'ALL')
                        table_access_rights(crs, user, is_group, t, 'GRANT', 'SELECT, INSERT')
                elif acc == 'query_access':
                    for t in all_tables:
                        table_access_rights(crs, user, is_group, t, 'REVOKE', 'ALL')
                    for t in run_tables:
                        table_access_rights(crs, user, is_group, t, 'GRANT', 'SELECT')
                    for t in meta_tables: 
                        table_access_rights(crs, user, is_group, t, 'GRANT', 'SELECT')
                        # Special case - also query users shold be able to store queries!
                        if t == 'xml_files':
                            table_access_rights(crs, user, is_group, 'xml_files', 'GRANT', 'INSERT')
                else:
                    # user's that are scheduled to be removed - remove them permanently
                    for t in all_tables:
                        table_access_rights(crs, user, is_group, t, 'REVOKE', 'ALL')
                    sqlexe(crs, "DELETE FROM exp_access WHERE name = %s", None, (db_row[nim['name']], ))
                    
    except psycopg.Error, error_msg:
        print "#* ERROR: Could not fix the access rights."
        print "   Reason:", error_msg
        return False

    # The changes need still to be comitted!
    return True

def get_crs_column(crs, col_idx):
    """From a SQL query result, get column 'col_idx' from all result rows
    as a single sequence."""
    cols = []
    for row in crs.fetchall():
        cols.append(row[col_idx])
    return cols

#
# string functions
#

def mk_info_key(info):
    """Return a hashable key for the parameter/result info list."""
    key = ""
    for i in range(7):
        key += info[i]
        
    return key

def mk_enhanced_gp(txt):
    """Create proper text strings for gnuplot's enhanced terminals by
    adding parentheses where necessary. This might not work for ALL strings,
    but for the usual ones and won't break anything.
    For now, we just add '{}' around everything, which doesn't harm. To be
    improved when necessary."""

    rval = ""

    # We process each substring individually to make the check for multiple
    # "magic character" work on a per-word basis, not on the complete string.
    if txt is None:
        return rval
    for s in txt.replace('  ', ', ').split():
        try:
            word_in = s
            for sep in ['_', '^']:            
                idx = 0
                src = word_in
                word_out = ""
                # If the "magic character" appears multiple times in a string, we do escape
                # it because it makes no sense otherwise.
                cnt = src.count(sep)
                if cnt > 1:
                    word_out = src.replace(sep, "\\"+sep)
                elif cnt == 0:
                    word_out = src
                else:
                    while idx < len(src):
                        if src[idx] == sep:
                            idx += 1
                            word_out = src[:idx] + "{"
                            while idx < len(src) and src[idx].isalnum():
                                word_out += src[idx]
                                idx += 1
                            word_out += "}"
                            src = word_out + src[idx:]
                            idx += 2
                        else:
                            word_out += src[idx]
                            idx += 1
                word_in = word_out            
        except IndexError:
            # we should never get here, but who knows...
            print "#* WARNING: could not enhance label '%s'" % txt
            
        # make a proper "microsecond" unit label
        # TODO: this is not very elegant - should be improved.
        if s == "[us]":
            word_out = "[{/Symbol m}s]"

        rval += "%s " % word_out
        
    return rval.strip()


def str_to_number(s):
    """Strip all leading and trailing non-numbers elements from a string.
    These are all elements not in [+-e.0123456789]. This function can be made
    even smarter by giving it knowledge how a valid number looks like (only
    one +,-,e,. etc.)."""
    digits = [ '+', '-', 'e', 'E', '.', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' ]

    if not s or len(s) == 0:
        return s

    if False and pb_debug:
        print "#* DEBUG: str_to_number() input:", s
        
    lead_idx = 0
    trail_idx = len(s)-1

    # support ',' as decimal separator if no '.', but a single ',' is supplied
    if s.count(',') == 1 and s.count('.') == 0:
        s = s.replace(',', '.')

    # XXX why skip an 'e'?
    if not cmp(s[lead_idx], 'e'):
        lead_idx += 1
        
    # remove everything in front that does not represent a number
    done=False
    while not done:
        if not s[lead_idx] in digits:
            lead_idx += 1
            if lead_idx == trail_idx + 1:
                return ""
        elif s[lead_idx] =='e' or s[lead_idx] == 'E':
            # check if this is an exponent e, or just a stray e
            if len(s) > lead_idx + 1:
                if not s[lead_idx+1] in ('+', '-', '.', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' ):
                    # it is a stray e
                    lead_idx += 1
                    if lead_idx == trail_idx + 1:
                        return ""
            else:
                return ""
        else:
            done = True                
                
    # remove trailing non digits
    while trail_idx > lead_idx and not s[trail_idx] in digits:
        trail_idx -= 1
        
    # now, come the start of the string and find the first character not matching
    # our definition from above
    idx = lead_idx
    while idx < trail_idx:
        if not s[idx] in digits:
            trail_idx = idx
            break
        idx += 1
        
    # finally, last character must always be a pure digit
    while not s[trail_idx:trail_idx+1].isdigit() and trail_idx >= lead_idx:
        trail_idx -= 1
    
    if False and pb_debug:
        print "#* DEBUG: str_to_number() output:", s[lead_idx:trail_idx+1]
        
    return s[lead_idx:trail_idx+1]


def get_switch(valid_args, str):
    """Return the switch part of a command line argument
    (-x for '-x gaga', '--xy=' for '--xy=gaga')"""
    if valid_args.has_key(str):
        return str
    if find(str, '=') != -1:
        return split(str, '=', 1)[0] + '='
    if str[0] == '-' and len(str) == 2:
        return split(str, ' ', 1)[0]
    return None


def is_pow2(n):
    "Return True if n is a power of 2."
    if not isinstance(n, int):
        return False
    if n < 0:
        return False
    if n < 3:
        return True
    while n > 2:
        n /= 2
    return n == 2

def build_pow2_label(n):
    """Create a string which is used as label for power-of-2 multiples (e.g. '2Ki' for 2048)"""
    if not isinstance(n, int):
        return str(n)
    if n < 1024:
        tic = str(n)
    elif n < 1024*1024 and n % 1024 == 0:
        tic = '%sKi' % str(n/1024)
    elif n < 1024*1024*1024 and n % (1024*1024) == 0:
        tic = '%sMi' % str(n/(1024*1024))
    elif n < 1024*1024*1024*1024 and n % (1024*1024*1024) == 0:
        tic = '%sGi' % str(n/(1024*1024*1024))
    elif n < 1024*1024*1024*1024*1024 and n % (1024*1024*1024*1024) == 0:
        tic = '%sTi' % str(n/(1024*1024*1024))
    elif n < 1024*1024*1024*1024*1024*1024 and n % (1024*1024*1024*1024*1024) == 0:
        tic = '%sPi' % str(n/(1024*1024*1024))
    else:
        tic = str(n)
    return tic


def read_from_stdin(prompt):
    """Read from stdin until an empty line is entered. All text is returned as a
    single string; line breaks of the user a translated into whitespace. """
    text = ""
    inp = raw_input(prompt)
    while len(inp) > 0:
        # We could also add a newline, but we better leave the line-breaking
        # to perfbase, not to the user.
        text += inp + ' ' 
        inp = raw_input()

    return text


def print_formatted(text, indent, linelen):
    """Print a string of arbitrary length in a left-aligned block. Line breaks
    are applied at white spaces. The block is indented by 'indent' spaces,
    and the total line lenght is 'linelen'."""
    start = 0
    stop = 0
    spaces = ""
    while indent > 0:
        spaces += " "
        indent -= 1
        
    while True:
        stop = desc.find(' ', start+linelen)
        if stop > 0:
            print spaces + desc[start:stop]
            start = stop+1
        else:
            print spaces + desc[start:]
            break
    return

def mk_label(label, nodes):
    """Process a label string. For now, this means replacing a macro (format is
    '<fixed_id>') with the content of the <fixed> object defined in the query.
    The modified label is returned."""
    if label is None:
        return label
    
    replc_map = {}
    new_label = label
    
    for l in label.split('('):
        if l.count(')') == 1:
            fixed_id = l.split(')')[0]
            if nodes.has_key(fixed_id):
                replc_map['(%s)' % fixed_id] = nodes[fixed_id].get_content()

    for k,v in replc_map.iteritems():
        new_label = new_label.replace(k, v)
        
    return new_label

def mk_using_str(n_cols):
    """Buld a string for gnuplot like 'using 1:2'"""
    u = "using 1"

    for i in range(2,n_cols+1):
        u = u + ":" + str(i)

    return u

#
# time functions
#

def mk_timestamp(fmt=None, fname=None):
    if fmt is None:
        fmt = '%Y-%m-%d %H:%M:%S %Z%z'
    if not fname:
        dt = datetime(2004, 1, 1, 0, 0, 0)
        return dt.now().strftime(fmt)
    else:
        return strftime(fmt, localtime(getmtime(fname)))

def get_current_year():
    fmt = '%Y'
    dt = datetime(2004, 1, 1, 0, 0, 0)
    return dt.now().strftime(fmt)    


def secs_to_timestamp(secs):
    fmt = '%Y-%m-%d %H:%M:%S %Z%z'
    return strftime(fmt, localtime(secs))


#
# hash function (no longer in use)
#

def c_mul(a, b):
    return ((long(a) * b) & 0x7FFFFFFFFFFFFFFFL)


def string_hash(s):
    if not s:
        return 0 # empty
    value = ord(s[0]) << 7
    for char in s :
        value = c_mul(1000003, value) ^ ord(char)
    value = value ^ len(s)
    return value

#
# support functions for data processing
#

def build_param_mapping(param_sweeps, do_match, sweep_group = None):
    """Gets a dictionary which is a mapping of names to lists with alias names for each name.
    From these lists, a list of mappings (dictionaries) is created where a name is mapped
    to a single alias. All of these mappings combined are the permutation of the lists."""
    map_list = []

    len_list = []
    idx_list = []
    base_list = []
    n_params = len(param_sweeps)

    if not do_match:
        n_tuples = 1
    else:
        # something like 'maxint' is required here!
        n_tuples = 1024*1024*1024 
    for k,v in param_sweeps.iteritems():
        l = len(v)
        if not do_match:
            n_tuples *= l
            len_list.append(l)
        else:
            if l < n_tuples:
                n_tuples = l

        base_list.append(k)
        idx_list.append(0)

    for i in range(n_tuples):
        new_map = {}        
        for j in range(n_params):
            new_map[base_list[j]] = param_sweeps[base_list[j]][idx_list[j]]
        map_list.append(new_map)
        
        if not do_match:
            idx_list[0] += 1
            for j in range(n_params):
                if idx_list[j] == len_list[j]:
                    idx_list[j] = 0
                    if j + 1 < n_params:
                        idx_list[j+1] += 1
                else:
                    break
        else:
            for j in range(len(idx_list)):
                idx_list[j] += 1

    return map_list
   
def base_id(id):
    """Strip potential sweep suffix from an id."""
    if id.count(pb_sweep_suffix) == 0:
        return id
    else:
        return id[:id.find(pb_sweep_suffix)]
    
def sweep_idx(id):
    """Get the sweep suffix, if any. Return -1 if no index was found."""
    if id.count(pb_sweep_suffix) == 0:
        return -1
    else:
        return id[id.find(pb_sweep_suffix)+1:]


#
# additional math/statistic functions
#

def erfc(x):
    return lerfcc(x)

def lerfcc(x):
    """Returns the complementary error function erfc(x) with fractional
    error everywhere less than 1.2e-7.  Adapted from Numerical Recipies.
    
    Usage:   lerfcc(x)

    From: http://www.nmr.mgh.harvard.edu/Neural_Systems_Group/gary/python/stats.py
    """
    z = abs(x)
    t = 1.0 / (1.0+0.5*z)
    ans = t * math.exp(-z*z-1.26551223 + t*(1.00002368+t*(0.37409196+t*(0.09678418+t*(-0.18628806+t*(0.27886807+t*(-1.13520398+t*(1.48851587+t*(-0.82215223+t*0.17087277)))))))))
    if x >= 0:
        return ans
    else:
        return 2.0 - ans


#
# data processing function
#

def get_all_content(db, vname):
    """Return a sorted list of all unique content of a parameter/result 'vname' in database 'db'."""

    crs = db.cursor()
    unique_cntnt = []

    # does this value exist at all?
    sqlexe(crs, "SELECT name FROM exp_values WHERE name = '%s'" % vname)
    if crs.rowcount == 0:
        raise SpecificationError, "The value '%s' does not exist." % vname

    # Need to differentiate between only-once or multiple
    sqlexe(crs, "SELECT only_once FROM exp_values WHERE name = '%s'" % vname)
    if crs.rowcount > 0:
        if crs.fetchone()[0]:
            # Check the rundata_once table - that's easy... Ascending order (to be
            # made configurable?)
            sqlexe(crs, "SELECT DISTINCT %s FROM rundata_once ORDER BY %s ASC" % (vname, vname))
            if crs.rowcount > 0:
                for data_row in crs.fetchall():
                    if data_row[0] is not None:
                        unique_cntnt.append(data_row[0])
        else:
            # Need to check all rundata_* tables... sigh.
            # Now, with version 5, this is also only a single table which makes this query much faster.
            sqlexe(crs, "SELECT index FROM run_metadata WHERE active")
            run_filter = "WHERE "
            if crs.rowcount > 0:
                for rr in crs.fetchall():
                    run_filter += "pb_run_index=%d OR " % rr[0]
                run_filter = run_filter[:-3]
                
                sqlexe(crs, "SELECT DISTINCT %s FROM rundata %s ORDER BY %s ASC" % (vname, run_filter, vname))
                if crs.rowcount > 0:
                    for data_row in crs.fetchall():
                        if data_row[0] is not None:
                            unique_cntnt.append(data_row[0])
            
    crs.close()
    if pb_debug:
        print "#* DEBUG: unique content for", vname, unique_cntnt
    return unique_cntnt
