/*
   (c) 2006 NEC Europe C&C Research Laboratories
   Joachim Worringen <joachim@ccrl-nece.de>

   This file is part of perfbase.

   perfbase is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   perfbase is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with perfbase; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

*/

#ifndef _PB_VERSION_NBR_H_
#define _PB_VERSION_NBR_H_

#include <stdio.h>
#include <string.h>
#include <sys/types.h>

#include <postgres.h>


#ifdef TESTING
#undef elog
#define elog     fprintf
#undef ERROR
#define ERROR    stderr
#undef palloc
#define palloc   malloc
#undef bool
#define bool     int
#endif

#define RTYPE_LEN   14

typedef struct v_nbr {
    /* v_M, v_m, v_u, v_r, v_q */
    short v[5];
    char  rt[RTYPE_LEN];
} version_nbr;


version_nbr *version_nbr_in(char *str);
char *version_nbr_out(version_nbr *v);
bool *version_nbr_eq(version_nbr *v1, version_nbr *v2);
bool *version_nbr_ne(version_nbr *v1, version_nbr *v2);
bool *version_nbr_lt(version_nbr *v1, version_nbr *v2);
int version_nbr_lt_int(version_nbr *v1, version_nbr *v2);
bool *version_nbr_gt(version_nbr *v1, version_nbr *v2);
bool *version_nbr_ge(version_nbr *v1, version_nbr *v2);
bool *version_nbr_le(version_nbr *v1, version_nbr *v2);


#endif
