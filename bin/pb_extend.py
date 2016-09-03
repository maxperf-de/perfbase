# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_extend - Extend the functionality of PostgreSQL
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

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg


def create_datatype_version_nbr(db, crs):
    """Create new scalar SQL datataype 'version_nbr'."""
    db.commit()
    rc = True
    
    if be_verbose():
        print "#* Creating SQL datatype 'version_nbr'"

    # This command may fail; we just execute it here to be sure that everything
    # concerning this type is removed from the database.
    try:
        crs.execute("DROP TYPE version_nbr CASCADE;")
    except psycopg.ProgrammingError:
        # end this erreanous transaction before continuing
        db.commit()

    sql_cmd = """
CREATE FUNCTION version_nbr_in(opaque)
	RETURNS version_nbr AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE FUNCTION version_nbr_out(opaque)
	RETURNS opaque AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE TYPE version_nbr (
	internallength=24,
	input=version_nbr_in,
	output=version_nbr_out
);

CREATE FUNCTION version_nbr_eq(version_nbr, version_nbr)
	RETURNS bool AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE FUNCTION version_nbr_ne(version_nbr, version_nbr)
	RETURNS bool AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE FUNCTION version_nbr_lt(version_nbr, version_nbr)
	RETURNS bool AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE FUNCTION version_nbr_lt_int(version_nbr, version_nbr)
	RETURNS int AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE FUNCTION version_nbr_le(version_nbr, version_nbr)
	RETURNS bool AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE FUNCTION version_nbr_gt(version_nbr, version_nbr)
	RETURNS bool AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE FUNCTION version_nbr_ge(version_nbr, version_nbr)
	RETURNS bool AS 'libvnbr.so'
	LANGUAGE 'c';

CREATE OPERATOR <> (
	leftarg = version_nbr,
	rightarg = version_nbr,
	procedure = version_nbr_ne,
	restrict = neqsel,
	join = neqjoinsel,
	commutator = <>,
	negator = =
);

CREATE OPERATOR < (
	leftarg = version_nbr,
	rightarg = version_nbr,
	procedure = version_nbr_lt,
	restrict = scalarltsel,
	join = scalarltjoinsel,
	commutator = >,
	negator = >=
);

CREATE OPERATOR <= (
	leftarg = version_nbr,
	rightarg = version_nbr,
	procedure = version_nbr_le,
	restrict = scalarltsel,
	join = scalarltjoinsel,
	commutator = >=,
	negator = >
);

CREATE OPERATOR > (
	leftarg = version_nbr,
	rightarg = version_nbr,
	procedure = version_nbr_gt,
	restrict = scalargtsel,
	join = scalargtjoinsel,
	commutator = <,
	negator = <=
);

CREATE OPERATOR >= (
	leftarg = version_nbr,
	rightarg = version_nbr,
	procedure = version_nbr_ge,
	restrict = scalargtsel,
	join = scalargtjoinsel,
	commutator = <=,
	negator = <
);

CREATE OPERATOR = (
	leftarg = version_nbr,
	rightarg = version_nbr,
	procedure = version_nbr_eq,
	restrict = eqsel,
	join = eqjoinsel,
	commutator = =,
	negator = <>,
        sort1 = <,
        sort2 = <
);

CREATE OPERATOR CLASS version_nbr_ops
    DEFAULT FOR TYPE version_nbr USING btree AS
        OPERATOR        1       < ,
        OPERATOR        2       <= ,
        OPERATOR        3       = ,
        OPERATOR        4       >= ,
        OPERATOR        5       > ,
        FUNCTION        1       version_nbr_lt_int(version_nbr, version_nbr);

"""

    if do_debug():
        print "DEBUG: SQL for new datatype:"
        print sql_cmd
        
    try:
        crs.execute(sql_cmd)
    except psycopg.Error, error_msg:
        print "#* ERROR: creating SQL datatype 'version_nbr' failed."
        print error_msg
        rc = False
    db.commit()

    return rc
