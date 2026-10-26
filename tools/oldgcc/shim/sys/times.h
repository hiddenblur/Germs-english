/* shim for mingw: gcc only uses times() for -ftime-report style statistics */
#ifndef SHIM_SYS_TIMES_H
#define SHIM_SYS_TIMES_H
#include <time.h>
struct tms { long tms_utime, tms_stime, tms_cutime, tms_cstime; };
static long times(struct tms *t) { long c = (long)clock(); if (t) { t->tms_utime = c; t->tms_stime = t->tms_cutime = t->tms_cstime = 0; } return c; }
#ifndef HZ
#define HZ CLOCKS_PER_SEC
#endif
#endif
