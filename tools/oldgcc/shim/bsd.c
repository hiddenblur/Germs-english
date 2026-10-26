/* BSD string functions old gcc expects from libc; mingw does not provide them. */
#include <string.h>
int bcmp(const void *a, const void *b, unsigned n) { return memcmp(a, b, n); }
char *index(const char *s, int c) { return strchr(s, c); }
char *rindex(const char *s, int c) { return strrchr(s, c); }
void bcopy(const void *s, void *d, unsigned n) { memmove(d, s, n); }
void bzero(void *d, unsigned n) { memset(d, 0, n); }
