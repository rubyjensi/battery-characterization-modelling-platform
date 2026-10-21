"""
battery_analysis.py
Analyse a discharge log from the ESP32 rig (18650 cell + resistor load).

Computes: capacity (Ah), true usable capacity, DoD vs time, State of Health,
internal resistance (DC step method), and plots the discharge curve.

Usage:
    python battery_analysis.py battery_log.csv --rated 3.4 --cutoff 2.8

Expected CSV columns (names are matched loosely, case-insensitive):
    time (seconds, or a datetime string), voltage (V), current (A), temp (C)
Current is assumed NEGATIVE during discharge (as your logger writes it); the script
flips it so graphs and calculations show discharge current as positive.
Use --current-sign 1 if your log has positive discharge current.
If your logger gives mA, use --current-scale 0.001
"""
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def find_col(df, keys):
    for c in df.columns:
        if any(k in c.lower() for k in keys):
            return c
    raise SystemExit(f"Could not find a column matching {keys}. Columns: {list(df.columns)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--rated", type=float, default=3.4, help="rated capacity in Ah (datasheet)")
    ap.add_argument("--cutoff", type=float, default=2.8, help="cutoff voltage in V")
    ap.add_argument("--current-scale", type=float, default=1.0, help="multiply current column to get A")
    ap.add_argument("--load-threshold", type=float, default=0.05, help="A, current above this = load connected")
    ap.add_argument("--current-sign", type=int, choices=[-1, 1], default=-1,
                    help="sign of current in the CSV during discharge (-1 = negative while discharging, default)")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    tcol = find_col(df, ["time", "stamp", "sec"])

    # If the log contains several sessions appended together (time jumps back to ~0),
    # keep only the last session.
    t_raw = pd.to_numeric(df[tcol], errors="coerce")
    resets = np.where(np.diff(t_raw.to_numpy()) < 0)[0]
    if len(resets):
        df = df.iloc[resets[-1] + 1:].reset_index(drop=True)
        print(f"Note: time restarted {len(resets)} time(s) in the file; analysing only the last session "
              f"({len(df)} rows).")
    vcol = find_col(df, ["volt", "v_"]) if any("volt" in c.lower() for c in df.columns) else find_col(df, ["v"])
    icol = find_col(df, ["curr", "amp", "i_"])

    # time -> seconds from start
    t = pd.to_numeric(df[tcol], errors="coerce")
    if t.isna().mean() > 0.5:
        t = (pd.to_datetime(df[tcol]) - pd.to_datetime(df[tcol]).iloc[0]).dt.total_seconds()
    t = t - t.iloc[0]
    v = df[vcol].astype(float).to_numpy()
    # CSV current is negative while discharging; multiply by -1 so discharge current
    # is positive everywhere below (capacity, heat, plots).
    i = df[icol].astype(float).to_numpy() * args.current_scale * args.current_sign
    t = t.to_numpy()

    # Optional temperature column (deg C)
    tempcol = next((c for c in df.columns if any(k in c.lower() for k in ["temp", "deg"])), None)
    temp = df[tempcol].astype(float).to_numpy() if tempcol else None
    if temp is not None:
        # -127 (and similar) is a DS18B20 "sensor not found" error code, not a temperature
        temp = np.where(temp <= -100, np.nan, temp)
        if np.isnan(temp).all():
            print("Note: temperature column only contains sensor errors (-127); skipping thermal analysis.")
            temp = None
        else:
            temp = pd.Series(temp).interpolate(limit_direction="both").to_numpy()

    # Use only the discharge portion down to the cutoff voltage
    loaded = i > args.load_threshold
    if not loaded.any():
        raise SystemExit("No loaded samples found; check current column / threshold "
                         f"(max discharge current seen: {i.max() * 1000:.1f} mA, threshold "
                         f"{args.load_threshold * 1000:.0f} mA).")
    start = np.argmax(loaded)
    if v[start] <= args.cutoff:
        raise SystemExit(f"Voltage is already {v[start]:.2f} V (at or below the {args.cutoff} V cutoff) "
                         "when the load connects, so there is no discharge to analyse. "
                         "Check the voltage measurement/wiring, or that the cell is charged.")
    below = np.where((v <= args.cutoff) & loaded)[0]
    end = below[0] if len(below) else len(v) - 1
    if end - start < 2:
        raise SystemExit("Fewer than 3 loaded samples before the cutoff; log a longer discharge.")
    ts, vs, is_ = t[start:end + 1], v[start:end + 1], i[start:end + 1]

    # Capacity by trapezoidal integration of current (coulomb counting)
    dt = np.diff(ts)
    ah_step = 0.5 * (is_[1:] + is_[:-1]) * dt / 3600.0
    ah_cum = np.concatenate([[0.0], np.cumsum(ah_step)])
    usable = ah_cum[-1]

    # Wh delivered (useful for energy comparison)
    wh = np.sum(0.5 * (is_[1:] * vs[1:] + is_[:-1] * vs[:-1]) * dt) / 3600.0

    soh = 100.0 * usable / args.rated
    dod = 100.0 * ah_cum / usable          # relative to true usable capacity
    dod_rated = 100.0 * ah_cum / args.rated  # relative to rated capacity
    soc = 100.0 - dod

    # Internal resistance: DC step method at load connect
    # OCV = average voltage of the ~5 samples before the load connects
    # V_load = average of samples just after (settled for a few samples)
    r_int = None
    v_rest = v_load = i_load = ir_drop = None
    if start >= 3:
        n_rest = min(5, start)
        v_rest = np.mean(v[start - n_rest:start])           # open-circuit (rest) voltage
        i_load = np.mean(i[start + 1:start + 4])
        v_load = np.mean(v[start + 1:start + 4])            # voltage just after load connects
        if i_load > 0:
            ir_drop = v_rest - v_load                       # IR drop (V)
            r_int = ir_drop / i_load                        # DC internal resistance (Ohm)

    usable_mah = usable * 1000.0
    print(f"Samples used            : {len(ts)}")
    print(f"Discharge duration      : {ts[-1] / 60:.1f} min")
    print(f"True usable capacity    : {usable_mah:.0f} mAh = {usable:.3f} Ah  (to {args.cutoff} V cutoff)")
    print(f"Energy delivered        : {wh:.2f} Wh")
    print(f"State of Health         : {soh:.1f} %  (usable {usable_mah:.0f} mAh / rated {args.rated * 1000:.0f} mAh)")
    print(f"Final DoD (vs rated)    : {dod_rated[-1]:.1f} %")
    if r_int is not None:
        print(f"IR drop at load step    : {ir_drop * 1000:.0f} mV  ({v_rest:.3f} V rest -> {v_load:.3f} V at {i_load * 1000:.0f} mA)")
        print(f"DC internal resistance  : {r_int * 1000:.1f} mOhm  (R = IR drop / I)")
    else:
        print("DC internal resistance  : need >=3 rest (no-load) samples before the load connects")

    # One-row summary of the headline numbers
    pd.DataFrame([{
        "usable_capacity_mAh": usable_mah,
        "usable_capacity_Ah": usable,
        "rated_capacity_mAh": args.rated * 1000.0,
        "SoH_pct": soh,
        "rest_voltage_V": v_rest,
        "loaded_voltage_V": v_load,
        "load_current_mA": None if i_load is None else i_load * 1000.0,
        "IR_drop_mV": None if ir_drop is None else ir_drop * 1000.0,
        "R_int_mOhm": None if r_int is None else r_int * 1000.0,
        "energy_Wh": wh,
    }]).to_csv("battery_summary.csv", index=False)

    summary_txt = (f"Usable capacity: {usable_mah:.0f} mAh ({usable:.3f} Ah)    "
                   f"SoH: {soh:.1f} %    ")
    if r_int is not None:
        summary_txt += f"IR drop: {ir_drop * 1000:.0f} mV    DC internal resistance: {r_int * 1000:.1f} mOhm"
    else:
        summary_txt += "DC internal resistance: n/a (no rest samples before load)"

    out = pd.DataFrame({"time_s": ts, "voltage_V": vs, "current_A": is_,
                        "capacity_Ah": ah_cum, "DoD_pct": dod, "SoC_pct": soc})

    # ---------------- Thermal behaviour ----------------
    has_thermal = temp is not None
    if has_thermal:
        # smooth the sensor noise (moving average over ~30 s, at least 5 samples)
        dt_med = np.median(np.diff(t)) if len(t) > 1 else 1.0
        win = int(max(5, round(30.0 / max(dt_med, 1e-6))))
        tm_full = pd.Series(temp).rolling(win, center=True, min_periods=1).mean().to_numpy()
        tm = tm_full[start:end + 1]
        t_amb = np.mean(temp[max(0, start - 5):start]) if start >= 1 else tm[0]

        dT = tm - t_amb
        dTdt = np.gradient(tm, ts)  # deg C per second

        # Heat generation: irreversible heat = I * (V_rest - V)  (overpotential heating)
        v_ref = np.mean(v[max(0, start - 5):start]) if start >= 1 else vs[0]
        q_gen_w = np.clip(is_ * (v_ref - vs), 0, None)           # W
        q_joule_w = is_ ** 2 * r_int if r_int else None          # W, I^2 R only
        q_total_wh = np.sum(0.5 * (q_gen_w[1:] + q_gen_w[:-1]) * dt) / 3600.0

        # Lumped thermal model fit:  dT/dt = a*Q - b*(T - T_amb)
        #   a = 1/C_th (K/J),  b = 1/(C_th*R_th) (1/s)
        Cth = Rth = None
        try:
            q_fit = q_joule_w if q_joule_w is not None else q_gen_w  # I^2*R is the cleaner heat source
            A = np.column_stack([q_fit, -dT])
            sol, *_ = np.linalg.lstsq(A, dTdt, rcond=None)
            a, b = sol
            if a > 0 and b > 0:
                Cth = 1.0 / a        # J/K
                Rth = 1.0 / (b * Cth)  # K/W
        except Exception:
            pass

        # temperature after load is removed (cool-down) is not used here
        print("---- Thermal ----")
        print(f"Ambient/start temp      : {t_amb:.1f} C")
        print(f"Peak temp               : {tm.max():.1f} C  (rise {dT.max():.1f} C)")
        print(f"Max heating rate        : {dTdt.max() * 60:.2f} C/min")
        print(f"Heat generated (I*dV)   : {q_total_wh:.3f} Wh  ({100 * q_total_wh / wh:.1f} % of delivered energy)")
        if q_joule_w is not None:
            print(f"Avg I^2*R heating       : {np.mean(q_joule_w) * 1000:.0f} mW")
        if Cth:
            print(f"Fitted C_th             : {Cth:.1f} J/K")
            print(f"Fitted R_th             : {Rth:.1f} K/W")
        else:
            print("Thermal model fit       : not reliable (temp rise too small or too noisy)")

        out["temp_C"] = tm
        out["dTemp_C"] = dT
        out["heat_W"] = q_gen_w

    out.to_csv("battery_results.csv", index=False)

    ncols = 3 if has_thermal else 2
    fig, ax = plt.subplots(1, ncols, figsize=(6 * ncols, 4.5))
    ax[0].plot(ah_cum * 1000, vs)
    ax[0].set_xlabel("Discharged capacity (mAh)")
    ax[0].set_ylabel("Voltage (V)")
    ax[0].set_title("Discharge curve (V vs capacity)")
    ax[0].grid(True)
    ax[1].plot(ts / 60, dod, color="tab:green", label="DoD")
    ax[1].set_xlabel("Time (min)")
    ax[1].set_ylabel("DoD (%)", color="tab:green")
    ax[1].set_title("DoD and discharge current vs time")
    ax[1].grid(True)
    axc = ax[1].twinx()
    axc.plot(ts / 60, is_ * 1000, color="tab:orange", alpha=0.8, label="Current")
    axc.set_ylabel("Discharge current (mA, sign flipped to +)", color="tab:orange")
    if has_thermal:
        ax[2].plot(ts / 60, tm, color="tab:red", label="Cell temp")
        ax[2].set_xlabel("Time (min)")
        ax[2].set_ylabel("Temperature (C)", color="tab:red")
        ax[2].set_title("Thermal behaviour")
        ax[2].grid(True)
        ax2 = ax[2].twinx()
        ax2.plot(ts / 60, q_gen_w * 1000, color="tab:blue", alpha=0.6, label="Heat (mW)")
        ax2.set_ylabel("Heat generation (mW)", color="tab:blue")
    plt.tight_layout(rect=(0, 0.08, 1, 1))
    fig.text(0.5, 0.025, summary_txt, ha="center", va="center", fontsize=11, fontweight="bold",
             bbox=dict(boxstyle="round,pad=0.5", fc="#f2f2f2", ec="#888888"))
    plt.savefig("discharge_graph.png", dpi=150)
    plt.show()


if __name__ == "__main__":
    main()