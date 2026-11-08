# Heroes III–style base damage rolls (reference for this mod)

This note summarizes how **Heroes of Might and Magic III** (_HoMM3_, SoD / Complete and typical fan patches) resolves **physical creature damage** at the **base damage** step—that is, **before** luck, specialties, spells, walls, and other modifiers are layered on. The in-game forecast in **Olden Era** may differ in edge cases; this mod uses the HoMM3 model as an **explicit estimate** for the shape of the total-damage distribution.

Sources: community testing, [Heroes III Wiki – Damage](https://homm.fandom.com/wiki/Damage), [Heroes Community – base damage threads](http://heroescommunity.com/viewthread.php3?TID=20955), and long-standing calculator write-ups (e.g. [HoMM3 damage calculator](https://dusanmilosavljevic1624.github.io/homm3-calc/)).

---

## 1. Per-creature damage interval

Each creature type has an integer damage spread **`[d_min, d_max]`** (shown in the unit stat block, e.g. “1–3”). For one attacking creature, base damage for that creature is a **single uniform discrete draw**:

\[
X \sim \mathrm{Uniform}\{d_{\min}, d_{\min}+1, \ldots, d_{\max}\}
\]

Every value in that interval has equal probability:

\[
\mathbb{P}(X = k) = \frac{1}{d_{\max} - d_{\min} + 1}.
\]

There is **no** normal distribution at this layer—it is literally a finite uniform over integers.

---

## 2. Stacks of size **N ≤ 10**

Each creature in the attacking stack rolls **independently** from the same `[d_min, d_max]`. Total **base damage** is the **sum** of **N** i.i.d. uniforms:

\[
S_N = X_1 + X_2 + \cdots + X_N.
\]

So:

- Minimum possible total base damage is **`N · d_min`** (every creature rolls its minimum).
- Maximum possible total base damage is **`N · d_max`** (every creature rolls its maximum).

The probability mass function of \(S_N\) is the **N-fold convolution** of one discrete uniform on `[d_min, d_max]` with itself **N** times—not a single uniform on `[N·d_min, N·d_max]`. The distribution is **unimodal**, with higher probability near the mean than at the extremes (Classic “bell-ish” histogram on a finite range).

---

## 3. Stacks of size **N > 10** (the “10 rolls” rule)

HoMM3 does **not** roll separately for every creature once the stack is large. Instead (standard description):

1. Perform **10** independent rolls, each uniform on **`[d_min, d_max]`**, and add them:

   \[
   T = Y_1 + Y_2 + \cdots + Y_{10}.
   \]

2. Scale that sum to the actual stack size using **integer** arithmetic (truncation toward zero for non-negative values matches **floor**):

   \[
   \text{BaseDamage} = \left\lfloor \frac{T \cdot N}{10} \right\rfloor
   \quad\text{equivalently for integers}\quad
   \frac{T \cdot N}{10}\ \text{using integer division.}
   \]

So for large stacks, only **10** underlying uniform draws drive randomness; the stack size enters **linearly** through the factor **N/10**. This keeps variance from growing as if you had literally **N** independent rolls, while matching the mean scaling of full stacks.

---

## 4. After base damage: modifiers (out of scope for the PMF shape here)

In HoMM3, **final** damage applies multiplicative and additive modifiers (attack/defense skill gap, offense/armorer, specials, spells, obstacles, etc.). **Luck** can double damage on a separate roll; **bad luck** can halve it in some versions.

This mod’s **luck / crit** handling remains in **`LuckCritMixture`** (aligned with Olden Era’s own balance data where possible), applied **after** the HoMM3-style **base** total-damage PMF.

---

## 5. How we map engine forecasts onto \(d_{\min}, d_{\max}\)

The game’s forecast DTO (`ejy`) exposes **total** squad damage bounds **`cgau`–`cgav`** for the current preview. Treat those as:

\[
\texttt{total\_min} \approx N \cdot d_{\min}, \qquad \texttt{total\_max} \approx N \cdot d_{\max}.
\]

We recover integer per-creature bounds with:

\[
d_{\min} = \left\lfloor \frac{\texttt{cgau}}{N} \right\rfloor, \qquad
d_{\max} = \left\lfloor \frac{\texttt{cgav}}{N} \right\rfloor
\]

using the same integer division as the existing code path (`totalMin / stackCount`, `totalMax / stackCount`). If the engine uses rounding or non-linear scaling, these are **approximate**; the HoMM3 convolution still gives the **intended** spread model.

---

## 6. Implementation summary (`DamageDistribution`)

| Stack size | Base total damage PMF in this mod |
|------------|-----------------------------------|
| **N ≤ 10** | Exact **N-fold convolution** of discrete uniform on `[d_min, d_max]` when **N** ≤ `convolutionMaxUnits`; otherwise Gaussian approximation on the same support. |
| **N > 10** | PMF of **T** = sum of **10** uniforms, then map each outcome with prob **p** to **`(T * N) / 10`** (integer division), merging mass on collisions. |

This replaces the earlier “single roll on total min/max” shortcut and restores **per-creature** roll structure consistent with HoMM3.

---

## 7. Disclaimer

Olden Era is **not** byte-for-byte HoMM3. This document describes the **classical III rules** used as a **deliberate model** for histogram spread. If future testing shows Olden Era uses different stack thresholds or scaling, adjust the thresholds (`10`) or the scaling branch in code accordingly.
