# KV8000 Test Parameter Config Design

## Goal

Replace dummy init parameters in `kv8000.json` with real production parameters from the KV8000 PLC parameter database, selecting a representative subset for testing.

## Context

- Source: `docs/t_biz_kv8000_param_202603020817.txt` (1216 params, one production line)
- Each production line has two devices: yb101 (equip_id=3) and yb102 (equip_id=5), representing A/B (left/right) sides
- Both devices are register ranges within the same KV8000 PLC (same IP/port)
- One gateway instance per production line
- For testing: use local JSON config; production will fetch from ThingsBoard Edge attributes

## Key Decisions

1. **Gateway uses `variable` column as telemetry key** - not `address_represent`. The address naming correction (e.g., GLUE_TIME_1 is actually GT2) is handled in ThingsBoard Edge's rule engine for PID/SPC calculations.

2. **Gateway does not map read-to-write addresses** - ThingsBoard Edge sends the correct write address in the RPC. Gateway just writes to whatever address it receives.

3. **Flat config, no code changes** - Just replace the dummy params in kv8000.json. No grouping, filtering, or generator scripts needed.

## Address Naming Mismatch (Documentation)

Some parameter variable names don't match the actual physical meaning. The `address_represent` column carries the correction:

| Variable Name | address_represent | Actual Meaning |
|---|---|---|
| GLUE_TIME_1 | R_GT2 | Reads GT2 (not GT1) |
| GLUE_TIME_2 | R_GT1 | Reads GT1 (not GT2) |
| AutoAdjust_X1 | W_EY2 | Writes EY2 (X/Y and 1/2 swapped) |
| AutoAdjust_Y1 | W_EX2 | Writes EX2 |
| AutoAdjust_X2 | W_EY1 | Writes EY1 |
| AutoAdjust_Y2 | W_EX1 | Writes EX1 |

This mapping is NOT handled by the gateway. ThingsBoard Edge resolves it.

## Config Structure

```
kv8000.json
  pollIntervalMs: 3000
  devices:
    ├── KV8000-YB101 (same PLC IP)
    │     parameters: 16 test params
    │       ├── 10 process read (REAL + DINT mix)
    │       ├── 2 AutoAdjust write (REAL)
    │       ├── 2 AutoAdjust readback (REAL)
    │       └── 2 alarm BOOL
    └── KV8000-YB102 (same PLC IP)
          parameters: 16 test params (mirrored addresses)
```

## Parameter Selection

### Per Device: 16 params (10 process + 2 write + 2 readback + 2 alarm)

#### Process Read Params (10)

| # | Variable (yb101) | Type | Addr (yb101) | Addr (yb102) |
|---|---|---|---|---|
| 1 | PC_VSBM_Potting_POTTING_CYCLE_TIME | REAL | DM10000 | DM12000 |
| 2 | PC_VSBM_Bonding_BONDING_OUTPUT | DINT | DM10006 | DM12006 |
| 3 | PC_VSBM_Potting_GLUE_TIME_1 | REAL | DM10016 | DM12016 |
| 4 | PC_VSBM_Potting_GLUE_TIME_2 | REAL | DM10018 | DM12018 |
| 5 | PC_VSBM_Bonding_SBB_NOZZLE_LIFE | DINT | DM10012 | DM12012 |
| 6 | PC_VSBM_Bonding_BLOW_H_H_TIME | REAL | DM10060 | DM12060 |
| 7 | PC_VSBM_Bonding_BOND_PAD_PITCH_1 | DINT | DM10032 | DM12032 |
| 8 | PC_VSBM_Bonding_1ST_LASER_PAD_1_ENERGY | DINT | DM10074 | DM12074 |
| 9 | PC_VSBM_Potting_GLUE_POSI_X_1 | DINT | DM10174 | DM12174 |
| 10 | PC_VSBM_Potting_CURRENT_WORKPIECE_NO | DINT | DM10376 | DM12376 |

#### AutoAdjust Write Params (2)

| # | Variable (yb101) | Type | Addr (yb101) | Addr (yb102) |
|---|---|---|---|---|
| 11 | PC_W_VSBM_AutoAdjust_GLUE_TIME_1 | REAL | DM13500 | DM14500 |
| 12 | PC_W_VSBM_AutoAdjust_GLUE_TIME_2 | REAL | DM13502 | DM14502 |

#### AutoAdjust Readback Params (2)

| # | Variable (yb101) | Type | Addr (yb101) | Addr (yb102) |
|---|---|---|---|---|
| 13 | PC_W_VSBM_AutoAdjust_GLUE_TIME_1_R | REAL | DM13518 | DM14018 |
| 14 | PC_W_VSBM_AutoAdjust_GLUE_TIME_2_R | REAL | DM13520 | DM14020 |

#### Alarm Params (2)

| # | Variable (yb101) | Type | Addr (yb101) | Addr (yb102) |
|---|---|---|---|---|
| 15 | FP7_ALARM_1 (ESTOP) | BOOL | DM16000.0 | DM16100.0 |
| 16 | FP7_ALARM_177_W_STOP | BOOL | LR10000.0 | LR10100.0 |

## Data Flow

```
KV8000 PLC (one IP)
  ├── Read: yb101 DM10xxx process + DM13518-13520 readback + DM16000.0 + LR10000.0
  ├── Read: yb102 DM12xxx process + DM14018-14020 readback + DM16100.0 + LR10100.0
  ├── Write (RPC): yb101 DM13500-13502
  └── Write (RPC): yb102 DM14500-14502
       │
       ▼
  Gateway (KV8000 Connector, local config)
       │ telemetry keys = variable names (e.g., yb101_PC_VSBM_Potting_GLUE_TIME_1)
       ▼
  ThingsBoard Edge (rule engine: name correction, PID/SPC)
       ▼
  ThingsBoard Cloud
```

## Implementation

Single task: rewrite `tb_gateway_collect/config/kv8000.json` with the selected parameters. No code changes needed.
