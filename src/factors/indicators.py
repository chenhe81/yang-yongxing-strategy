"""因子计算函数库"""
import numpy as np
import pandas as pd

def RANK(s, pct=True):
    return s.rank(pct=True) - 0.5 if pct else s.rank()

def STDDEV(s, w=20):
    return s.rolling(w, min_periods=min(w//2,5)).std()

def CORRELATION(s1, s2, w=20):
    return s1.rolling(w, min_periods=min(w//2,5)).corr(s2)

def COVARIANCE(s1, s2, w=20):
    return s1.rolling(w, min_periods=min(w//2,5)).cov(s2)

def ABS(s): return s.abs()
def LOG(s): return np.log(s.clip(lower=1e-10))
def POWER(s, p): return s**p
def SIGN(s): return np.sign(s)
def MIN(s1, s2): return pd.concat([s1,s2],axis=1).min(axis=1)
def MAX(s1, s2): return pd.concat([s1,s2],axis=1).max(axis=1)
def IF(c, t, f): return np.where(c, t, f)

def DELAY(s, p=1): return s.shift(p)
def REF(s, N=1): return s.shift(N)
def DIFF(s, N=1): return s.diff(N)
def SUM(s, w=20): return s.rolling(w, min_periods=max(w//2,1)).sum()
def TS_MEAN(s, w=20): return s.rolling(w, min_periods=max(w//2,1)).mean()
def TS_MAX(s, w=20): return s.rolling(w, min_periods=max(w//2,1)).max()
def TS_MIN(s, w=20): return s.rolling(w, min_periods=max(w//2,1)).min()
def DECAY_LINEAR(s, w=20):
    wt = np.arange(1, w+1)
    wt = wt/wt.sum()
    return s.rolling(w).apply(lambda x: np.dot(x, wt[-len(x):]), raw=True)

def MA(s, w=20): return s.rolling(w, min_periods=max(w//2,1)).mean()
def EMA(s, w=20): return s.ewm(span=w, min_periods=max(w//2,1), adjust=False).mean()
def WMA(s, w=20):
    wt = np.arange(1, w+1); wt = wt/wt.sum()
    return s.rolling(w).apply(lambda x: np.dot(x, wt[-len(x):]), raw=True)
def BBI(s, m1=3, m2=6, m3=12, m4=20):
    return (MA(s,m1)+MA(s,m2)+MA(s,m3)+MA(s,m4))/4
def VWAP(c, v): return (c*v).cumsum() / v.cumsum().replace(0,np.nan)
def RETURNS(s, p=1): return s.pct_change(p)

def RSI(s, N=24):
    d = s.diff(); g = d.clip(lower=0).rolling(N).mean()
    l = (-d).clip(lower=0).rolling(N).mean()
    return 100 - 100/(1+g/l.replace(0,np.nan))

def MACD(c, SHORT=12, LONG=26, M=9):
    d = EMA(c,SHORT)-EMA(c,LONG)
    de = EMA(d, M)
    return d, de, 2*(d-de)

def KDJ(c, h, l, N=9, M1=3, M2=3):
    ln = l.rolling(N).min(); hn = h.rolling(N).max()
    rsv = (c-ln)/(hn-ln).replace(0,np.nan)*100
    k = rsv.ewm(span=M1,adjust=False).mean()
    d = k.ewm(span=M2,adjust=False).mean()
    return k, d, 3*k-2*d

def BOLL(c, N=20, P=2):
    m = MA(c,N); s = c.rolling(N).std()
    return m+P*s, m, m-P*s

def ATR(c, h, l, N=20):
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(N).mean()

def WR(c, h, l, N=10, N1=6):
    hh = h.rolling(N).max(); ll = l.rolling(N).min()
    return (hh-c)/(hh-ll).replace(0,np.nan)*(-100)

def BIAS(c, L1=6, L2=12, L3=24):
    return ((c-MA(c,L1))/MA(c,L1).replace(0,np.nan)*100,
            (c-MA(c,L2))/MA(c,L2).replace(0,np.nan)*100,
            (c-MA(c,L3))/MA(c,L3).replace(0,np.nan)*100)

def OBV(c, v): return (np.sign(c.diff())*v).fillna(0).cumsum()

def MFI(c, h, l, v, N=14):
    tp = (h+l+c)/3
    p = (tp*v).where(tp.diff()>0,0).rolling(N).sum()
    n = (tp*v).where(tp.diff()<0,0).rolling(N).sum()
    return 100-100/(1+p/n.replace(0,np.nan))

def PSY(c, N=12, M=6):
    p = (c.diff()>0).astype(float).rolling(N).sum()/N*100
    return p, MA(p,M)

def CROSS(s1, s2):
    return ((s1>s2) & (s1.shift()<=s2.shift())).astype(float)

def COUNT(c, N): return c.astype(float).rolling(N).sum()
def EVERY(c, N): return c.astype(float).rolling(N).min() > 0.5
def EXIST(c, N): return c.astype(float).rolling(N).max() > 0.5
def HHVBARS(s, N): return s.rolling(N).apply(lambda x: x.argmax(), raw=True)
def LLVBARS(s, N): return s.rolling(N).apply(lambda x: x.argmin(), raw=True)
def SLOPE(s, N):
    return s.rolling(N,min_periods=2).apply(lambda y: np.polyfit(np.arange(len(y)),y,1)[0], raw=True)

def FILTER(c, N):
    f = c.astype(float)
    for i in range(1,N): f = f & ~f.shift(i).fillna(0).astype(bool)
    return f.astype(float)

FUNCTION_REGISTRY = {
    "RANK": RANK, "STDDEV": STDDEV, "CORRELATION": CORRELATION, "COVARIANCE": COVARIANCE,
    "ABS": ABS, "LOG": LOG, "POWER": POWER, "SIGN": SIGN, "MIN": MIN, "MAX": MAX, "IF": IF,
    "DELAY": DELAY, "REF": REF, "DIFF": DIFF,
    "SUM": SUM, "TS_MEAN": TS_MEAN, "TS_MAX": TS_MAX, "TS_MIN": TS_MIN,
    "DECAY_LINEAR": DECAY_LINEAR,
    "MA": MA, "EMA": EMA, "WMA": WMA, "BBI": BBI,
    "VWAP": VWAP, "RETURNS": RETURNS,
    "RSI": RSI, "MACD": MACD, "KDJ": KDJ,
    "BOLL": BOLL, "ATR": ATR, "WR": WR, "BIAS": BIAS,
    "OBV": OBV, "MFI": MFI, "PSY": PSY,
    "CROSS": CROSS, "COUNT": COUNT, "EVERY": EVERY, "EXIST": EXIST,
    "HHVBARS": HHVBARS, "LLVBARS": LLVBARS,
    "SLOPE": SLOPE, "FILTER": FILTER,
}
MULTI_OUTPUT = {"MACD", "KDJ", "BOLL", "BIAS", "PSY"}
