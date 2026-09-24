"""Built-in starter templates and CP snippet library (editable in-app)."""

PYTHON_TEMPLATE = '''\
import sys
import math
from collections import defaultdict, Counter, deque

def solve():
    data = sys.stdin.buffer.read().split()
    it = iter(data)
    # n = int(next(it))
    # a = [int(next(it)) for _ in range(n)]
    # ... your code here
    
    # example output: sys.stdout.write(str(ans) + "\\n")

if __name__ == "__main__":
    solve()
'''

CPP_TEMPLATE = r'''#include <bits/stdc++.h>
using namespace std;
using ll = long long;
using vi = vector<int>;
using vll = vector<ll>;

#define all(x) (x).begin(), (x).end()
#define rep(i, a, b) for (int i = (a); i < (b); ++i)

int32_t main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n;
    cin >> n;
    // ... your code here
    cout << n << "\n";
    return 0;
}
'''

BUILTIN_SNIPPETS = [
    {
        "name": "Fast IO (cpp)",
        "language": "cpp",
        "content": r'''ios::sync_with_stdio(false);
cin.tie(nullptr);''',
    },
    {
        "name": "DSU (Union-Find)",
        "language": "cpp",
        "content": r'''struct DSU {
    vector<int> p, sz;
    DSU(int n) : p(n), sz(n, 1) { iota(p.begin(), p.end(), 0); }
    int find(int x) { return p[x] == x ? x : p[x] = find(p[x]); }
    bool unite(int a, int b) {
        a = find(a); b = find(b);
        if (a == b) return false;
        if (sz[a] < sz[b]) swap(a, b);
        p[b] = a; sz[a] += sz[b];
        return true;
    }
};''',
    },
    {
        "name": "Fenwick Tree",
        "language": "cpp",
        "content": r'''struct Fenwick {
    int n; vector<long long> bit;
    Fenwick(int n) : n(n), bit(n + 1) {}
    void add(int i, long long v) { for (; i <= n; i += i & -i) bit[i] += v; }
    long long sum(int i) { long long s = 0; for (; i > 0; i -= i & -i) s += bit[i]; return s; }
};''',
    },
    {
        "name": "Segment Tree (range sums)",
        "language": "cpp",
        "content": r'''struct SegTree {
    int n; vector<long long> t;
    SegTree(const vector<long long>& a) {
        n = a.size(); t.assign(2 * n, 0);
        for (int i = 0; i < n; ++i) t[n + i] = a[i];
        for (int i = n - 1; i > 0; --i) t[i] = t[i << 1] + t[i << 1 | 1];
    }
    void update(int p, long long v) { for (t[p += n] = v; p > 1; p >>= 1) t[p >> 1] = t[p] + t[p ^ 1]; }
    long long query(int l, int r) {  // [l, r)
        long long res = 0;
        for (l += n, r += n; l < r; l >>= 1, r >>= 1) {
            if (l & 1) res += t[l++];
            if (r & 1) res += t[--r];
        }
        return res;
    }
};''',
    },
    {
        "name": "modpow / modinv",
        "language": "cpp",
        "content": r'''long long modpow(long long b, long long e, long long mod) {
    long long r = 1 % mod;
    for (; e; e >>= 1) {
        if (e & 1) r = r * b % mod;
        b = b * b % mod;
    }
    return r;
}
// modular inverse (mod prime): modpow(a, mod-2, mod)''',
    },
    {
        "name": "Prime Sieve",
        "language": "cpp",
        "content": r'''vector<int> sieve(int n) {
    vector<bool> is(n + 1, true); is[0] = is[1] = false;
    for (int i = 2; i * i <= n; ++i) if (is[i])
        for (int j = i * i; j <= n; j += i) is[j] = false;
    vector<int> primes;
    for (int i = 2; i <= n; ++i) if (is[i]) primes.push_back(i);
    return primes;
}''',
    },
    {
        "name": "Binary search on answer",
        "language": "cpp",
        "content": r'''long long lo = 0, hi = 1e18;
while (lo < hi) {
    long long mid = (lo + hi + 1) / 2;
    if (check(mid)) lo = mid;
    else hi = mid - 1;
}''',
    },
    {
        "name": "Fast IO + reader (py)",
        "language": "python",
        "content": '''import sys
def solve():
    data = sys.stdin.buffer.read().split()
    it = iter(data)
    n = int(next(it))
    a = [int(next(it)) for _ in range(n)]
solve()''',
    },
    {
        "name": "LCM / GCD (py)",
        "language": "python",
        "content": '''from math import gcd
def lcm(a, b):
    return a // gcd(a, b) * b''',
    },
    {
        "name": "Primes sieve (py)",
        "language": "python",
        "content": '''def sieve(n):
    is_p = [True] * (n + 1)
    is_p[0] = is_p[1] = False
    for i in range(2, int(n ** 0.5) + 1):
        if is_p[i]:
            for j in range(i * i, n + 1, i):
                is_p[j] = False
    return [i for i in range(2, n + 1) if is_p[i]]''',
    },
    {
        "name": "Combinations (py)",
        "language": "python",
        "content": '''from math import comb, perm
# comb(n, k), perm(n, k) built in since 3.8''',
    },
    {
        "name": "Catalan number",
        "language": "both",
        "content": '''# C_n = (2n)! / ((n+1)! n!)
# c[0] = 1; c[n] = c[n-1] * (4n-2) / (n+1)''',
    },
]