
#include "version_nbr.h"

/* version_nbr.c 

   Not a 100% flexible, but efficient definition of a version number:
   Supported are version numbers that fit to something like 1.2.3.4rc1.
   Formally: 
     M.m.u.r<type>q
   where:
     M      major version number (integer)
     m      minor version number (integer)
     u      micro version number (integer)
     r      release version number (integer)
     <type> release type like "alpha", "rc" (max. 13-char string)
     q      quantifier (integer), releated to type
   
   All integer are signed short values. Valid values are >= 0. All values 
   except M may remain unassigned (internal value is -1).

   The release type is any non-numeric string in the version number; it must 
   only contain letters and '-'. The maximum lenght is 8 characters. A leading 
   '-' is omitted from the release type. All numbers following the type are 
   assigned to q. If anything follows q, an error is raised. The release type
   must not be empty for a q != -1.

   Sorting is done in "version style", which means *not* decimally, but 
   level-by-level: 1.19 is larger than 1.2. 

   Examples for valid version numbers:
   1.2-rc3        M=1, m=2, u=r=-1, type="rc", q=3   
   2.0.1 pre     M=2, m= 0, u=1, r=-1, type="pre", q=-1

   Examples for invalid version numbers:
   1.2.3.4.5      too many dots
   1.2.3 a1.4     only numbers must follow the release type

   For more tests, see test_vnbr.c.
*/

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

#define v_M   0
#define v_m   1
#define v_u   2
#define v_r   3
#define v_q   4
#define N_V   5

#define NBR   0
#define DOT   1
#define TXT   2

#define IS_NBR(s) ((s) >= 0x30 && (s) <= 0x39)
#define IS_DOT(s) ((s) == 0x2E)
#define IS_TXT(s) (((s) >= 0x41 && (s) <= 0x5A) || ((s) >= 0x61 && (s) <= 0x79) || (s) == 0x2D || (s) == 0x5F)
#define IS_WS(s)  ((s) == 0x09 || (s) == 0x20  || (s) == 0x2D || (s) == 0x5F)

#define TMP_LEN     32


version_nbr *version_nbr_in(char *str)
{
    version_nbr *new_v;
    short v[5];
    char rt[RTYPE_LEN];
    char tmp[TMP_LEN];
    int i, s, t, r;
    int expect, v_idx, n_dots;
    
    if (str == NULL || strlen(str) == 0) {
	elog(ERROR, "version_nbr_in: parse error (NULL ptr or empty string)");
	return NULL;
    }
	
    /* Can only process 7-bit ASCII -check! */
    for (i = 0; i < RTYPE_LEN; i++) {
	if (str[i] == '\0')
	    break;
	if (str[i] & 0x80) {
	    elog(ERROR, "version_nbr_in: parse error in %s:%d (only 7-bit ASCII is supported)", str, s);
	    return NULL;
	}
    }

    /* some more static tests */
    if (!IS_NBR(str[0])) {
	elog(ERROR, "version_nbr_in: parse error in %s:0 (must start with number)", str);
	return NULL;
    }

    /* 
     * Parse the input string. 
     */
    for (i = 0; i < N_V; i++)
	v[i] = -1;
    memset (rt, 0, RTYPE_LEN);
    memset (tmp, 0, TMP_LEN);

    expect = NBR;
    v_idx = v_M;
    s = t = r = n_dots = 0;
    while (str[s] != '\0') {
	switch (expect) {
	case NBR:
	    if (IS_NBR(str[s])) {
		tmp[t++] = str[s++];
		if (t >= TMP_LEN) {
		    elog(ERROR, "version_nbr_in: parse error in %s:%d (number too long)", str, s);
		    return NULL;
		}
	    } else if (IS_DOT(str[s]) || IS_TXT(str[s]) || IS_WS(str[s])) {
		if (IS_DOT(str[s])) {
		    if (++n_dots > 3) {
			elog(ERROR, "version_nbr_in: parse error in %s:%d (too many dots)", str, s);
			return NULL;
		    }
		    if (v_idx == v_q) {
			elog(ERROR, "version_nbr_in: parse error in %s:%d (dots in quantifier)", str, s);
			return NULL;
		    }
		}
		tmp[t] = '\0';
		v[v_idx++] = atoi(tmp);

		t = 0;
		memset (tmp, 0, TMP_LEN);

		if (IS_TXT(str[s]) || IS_WS(str[s])) {
		    if (strlen(rt) > 0) {
			elog(ERROR, "version_nbr_in: parse error in %s:%d (duplicate release type string)", str, s);
			return NULL;
		    }
		    if (IS_TXT(str[s]) && !IS_WS(str[s]))
			rt[r++] = str[s];
		    v_idx = v_q;
		}
		if (v_idx == v_q)
		    expect = TXT;
		s++;
	    } else {
		elog(ERROR, "version_nbr_in: parse error in %s:%d (invalid character '%c')", str, s, str[s]);
		return NULL;
	    }
	    break;
	case DOT:
	    /* will never get here */
	    break;
	case TXT:
	    if (IS_TXT(str[s])) {
		if (r == 0 && IS_WS(str[s])) {
		    s++;
		    break;
		}
		rt[r++] = str[s++];
		if (r >= RTYPE_LEN) {
		    elog(ERROR, "version_nbr_in: parse error in %s:%d (release type too long)", str, s);
		    return NULL;
		}
	    } else if (IS_WS(str[s])) {
		s++;
	    } else if (IS_NBR(str[s])) {
		rt[r] = '\0';
		tmp[t++] = str[s++];
		expect = NBR;
	    } else if (IS_DOT(str[s])) {
		elog(ERROR, "version_nbr_in: parse error in %s:%d (dots in release type)", str, s);
		return NULL;
	    } else {
		elog(ERROR, "version_nbr_in: parse error in %s:%d (invalid character '%c')", str, s, str[s]);
		return NULL;
	    }
		
	    break;
	}		      
    }
    if (expect == NBR && t > 0) {
	v[v_idx] = atoi(tmp);
    } else if (expect == TXT) {
	rt[r] = '\0';
    }
    
    new_v = (version_nbr *)palloc(sizeof(version_nbr));

    for (i = 0; i < N_V; i++)
	new_v->v[i] = v[i];
    strcpy(new_v->rt, rt);

    return new_v;
}


char *version_nbr_out(version_nbr *v)
{
    char *s, tmp[6];

    if (v == NULL)
	return NULL;

    /* max lenght is 3*(5+1) + 5 + 8 + 5 + 1 = 37 */
    s = (char *)palloc(40);
    
    sprintf(s, "%d", v->v[v_M]);
    if (v->v[v_m] >= 0) {
	sprintf(tmp, ".%d", v->v[v_m]);
	strcat (s, tmp);
    }
    if (v->v[v_u] >= 0) {
	sprintf(tmp, ".%d", v->v[v_u]);
	strcat (s, tmp);
    }
    if (v->v[v_r] >= 0) {
	sprintf(tmp, ".%d", v->v[v_r]);
	strcat (s, tmp);
    }
    if (strlen(v->rt) > 0) {
	strcat (s, v->rt);
    }
    if (v->v[v_q] >= 0) {
	sprintf(tmp, "%d", v->v[v_q]);
	strcat (s, tmp);
    }
	
    return s;
}


bool *version_nbr_eq(version_nbr *v1, version_nbr *v2)
{
    bool *rc;

    if (v1->v[v_M] == v2->v[v_M] 
	&& v1->v[v_m] == v2->v[v_m] 
	&& v1->v[v_u] == v2->v[v_u] 
	&& v1->v[v_r] == v2->v[v_r]
	&& v1->v[v_q] == v2->v[v_q] 
	&& !strcmp(v1->rt, v2->rt)) {
	rc = 1;
    } else {
	rc = 0;
    }
	
    return rc;
}


bool *version_nbr_ne(version_nbr *v1, version_nbr *v2)
{
    bool *rc;

    if (v1->v[v_M] != v2->v[v_M] 
	|| v1->v[v_m] != v2->v[v_m] 
	|| v1->v[v_u] != v2->v[v_u] 
	|| v1->v[v_r] != v2->v[v_r] 
	|| v1->v[v_q] != v2->v[v_q] 
	|| strcmp(v1->rt, v2->rt)) {
	rc = 1;
    } else {
	rc = 0;
    }

    return rc;
}


/* returns true if v1 < v2 */
bool *version_nbr_lt(version_nbr *v1, version_nbr *v2)
{
    bool *rc;
    int sc;

    /* major */
    if (v1->v[v_M] < v2->v[v_M]) {
	rc = 1;
    } else if (v1->v[v_M] > v2->v[v_M]) {
	rc = 0;
    } else {
	/* minor */
	if (v1->v[v_m] < v2->v[v_m])
	    rc = 1;
	else if (v1->v[v_m] > v2->v[v_m])
	    rc = 0;
	else {
	    /* micro */
	    if (v1->v[v_u] < v2->v[v_u])
		rc = 1;
	    else if (v1->v[v_u] > v2->v[v_u])
		rc = 0;
	    else {
		/* release */
		if (v1->v[v_r] < v2->v[v_r])
		    rc = 1;
		else if (v1->v[v_r] > v2->v[v_r])
		    rc = 0;
		else {
		    /* type */
		    sc = strcmp(v1->rt, v2->rt);
		    if (sc < 0)
			rc = 1;
		    else if (sc > 0)
			rc = 0;
		    else {
			/* quantity */
			if (v1->v[v_q] < v2->v[v_q])
			    rc = 1;
			else 
			    /* v1 is equal or larger than v2 */
			    rc = 0;
		    }
		}
	    }
	}
    }
    
    return rc;
}


/* wrapper for btree-function which requires a return value of type integer */
int version_nbr_lt_int(version_nbr *v1, version_nbr *v2)
{
  return (int)version_nbr_lt(v1, v2);
}


/* returns true if v1 <= v2 */
bool *version_nbr_le(version_nbr *v1, version_nbr *v2)
{
    bool *rc;
    int sc;

    /* major */
    if (v1->v[v_M] < v2->v[v_M]) {
	rc = 1;
    } else if (v1->v[v_M] > v2->v[v_M]) {
	rc = 0;
    } else {
	/* minor */
	if (v1->v[v_m] < v2->v[v_m])
	    rc = 1;
	else if (v1->v[v_m] > v2->v[v_m])
	    rc = 0;
	else {
	    /* micro */
	    if (v1->v[v_u] < v2->v[v_u])
		rc = 1;
	    else if (v1->v[v_u] > v2->v[v_u])
		rc = 0;
	    else {
		/* release */
		if (v1->v[v_r] < v2->v[v_r])
		    rc = 1;
		else if (v1->v[v_r] > v2->v[v_r])
		    rc = 0;
		else {
		    /* type */
		    sc = strcmp(v1->rt, v2->rt);
		    if (sc < 0)
			rc = 1;
		    else if (sc > 0)
			rc = 0;
		    else {
			/* quantity */
			if (v1->v[v_q] < v2->v[v_q])
			    rc = 1;
			else if (v1->v[v_q] > v2->v[v_q])
			    rc = 0;
			else 
			    /* v1 is equal to v2 */
			    rc = 1;
		    }
		}
	    }
	}
    }
    
    return rc;
}


/* returns true if v1 > v2 */
bool *version_nbr_gt(version_nbr *v1, version_nbr *v2)
{
    bool *rc;
    int sc;

    /* major */
    if (v1->v[v_M] > v2->v[v_M]) {
	rc = 1;
    } else if (v1->v[v_M] < v2->v[v_M]) {
	rc = 0;
    } else {
	/* minor */
	if (v1->v[v_m] > v2->v[v_m])
	    rc = 1;
	else if (v1->v[v_m] < v2->v[v_m])
	    rc = 0;
	else {
	    /* micro */
	    if (v1->v[v_u] > v2->v[v_u])
		rc = 1;
	    else if (v1->v[v_u] < v2->v[v_u])
		rc = 0;
	    else {
		/* release */
		if (v1->v[v_r] > v2->v[v_r])
		    rc = 1;
		else if (v1->v[v_r] < v2->v[v_r])
		    rc = 0;
		else {
		    /* type */
		    sc = strcmp(v1->rt, v2->rt);
		    if (sc > 0)
			rc = 1;
		    else if (sc < 0)
			rc = 0;
		    else {
			/* quantity */
			if (v1->v[v_q] > v2->v[v_q])
			    rc = 1;
			else 
			    /* v1 is smaller or equal than v2 */
			    rc = 0;
		    }
		}
	    }
	}
    }
    
    return rc;
}


/* returns true if v1 >= v2 */
bool *version_nbr_ge(version_nbr *v1, version_nbr *v2)
{
    bool *rc;
    int sc;

    /* major */
    if (v1->v[v_M] > v2->v[v_M]) {
	rc = 1;
    } else if (v1->v[v_M] < v2->v[v_M]) {
	rc = 0;
    } else {
	/* minor */
	if (v1->v[v_m] > v2->v[v_m])
	    rc = 1;
	else if (v1->v[v_m] < v2->v[v_m])
	    rc = 0;
	else {
	    /* micro */
	    if (v1->v[v_u] > v2->v[v_u])
		rc = 1;
	    else if (v1->v[v_u] < v2->v[v_u])
		rc = 0;
	    else {
		/* release */
		if (v1->v[v_r] > v2->v[v_r])
		    rc = 1;
		else if (v1->v[v_r] < v2->v[v_r])
		    rc = 0;
		else {
		    /* type */
		    sc = strcmp(v1->rt, v2->rt);
		    if (sc > 0)
			rc = 1;
		    else if (sc < 0)
			rc = 0;
		    else {
			/* quantity */
			if (v1->v[v_q] > v2->v[v_q])
			    rc = 1;
			else if  (v1->v[v_q] < v2->v[v_q])
			    /* v1 is smaller than v2  */
			    rc = 0;
			else 
			    /* v1 is equal to v2  */
			    rc = 1;
		    }
		}
	    }
	}
    }
    
    return rc;
}


