# FIX: Corrupted Entities Causing HTTP 400 Errors

**Date:** 2025-10-29
**Status:** ⚠️ REQUIRES MANUAL ACTION
**Severity:** HIGH (Blocking entity updates)

## Problem

Home Assistant API returns HTTP 400 errors when AppDaemon tries to update certain entities. Testing showed that **even minimal updates (state only, no attributes) fail**, indicating the entities themselves are corrupted in HA database.

## Root Cause

Entities became corrupted in Home Assistant entity registry, possibly due to:
- Previous updates with HA internal attributes (last_changed, context, etc.)
- Entity registry database corruption
- AppDaemon crashes during entity updates

## Corrupted Entities

Based on log analysis, these 6 entities are corrupted:

1. **sensor.event_queue_metrics** (15 errors)
2. **sensor.nasdaq_volume_zscore** (12 errors)
3. **sensor.trading_open_positions** (10 errors)
4. **sensor.dax_volume_zscore** (10 errors)
5. **sensor.trading_daily_pnl** (3 errors)
6. **sensor.trading_daily_pnl_percent** (likely also affected)

## Solution: Restart Home Assistant to Clear Temporary Entities

**CRITICAL DISCOVERY:** Entities created via AppDaemon's `set_state()` API **do not have unique_id**, which makes them "temporary" entities that:
- ❌ Cannot be deleted via Home Assistant UI
- ❌ Cannot be managed via Entity Registry
- ⚠️ May become corrupted and cause HTTP 400 errors

**Screenshot Evidence:**
```
"Tato entita ("sensor.nasdaq_volume_zscore") nemá jedinečné ID, proto
její nastavení nelze spravovat z uživatelského rozhraní."

Translation: "This entity does not have a unique ID, therefore its
settings cannot be managed from the user interface."
```

### Option 1: Restart Home Assistant Core (RECOMMENDED - FASTEST)

**This clears ALL temporary entities and forces recreation:**

1. **Via Home Assistant UI:**
   - Go to http://homeassistant.local:8123/
   - Click **Configuration** → **System** → **Restart**
   - Wait 2-3 minutes for restart to complete

2. **Via SSH:**
   ```bash
   ssh homeassistant
   ha core restart
   ```

3. **Wait for restart to complete:**
   - Home Assistant will restart (2-3 minutes)
   - AppDaemon will auto-restart when HA comes back
   - Entities will be recreated automatically

4. **Verify entities are recreated:**
   - Check logs for successful updates (no HTTP 400 errors)
   - Dashboard should show correct values

### Option 2: Manual Deletion via SSH and Entity Registry (ALTERNATIVE)

**WARNING:** This requires editing Home Assistant's internal database!

1. **Stop Home Assistant:**
   ```bash
   ssh homeassistant
   ha core stop
   ```

2. **Edit entity registry:**
   ```bash
   # Backup first!
   cp /config/.storage/core.entity_registry /config/.storage/core.entity_registry.backup

   # Remove entities (requires manual editing)
   vi /config/.storage/core.entity_registry
   ```

3. **Remove these entity entries:**
   - `sensor.event_queue_metrics`
   - `sensor.nasdaq_volume_zscore`
   - `sensor.trading_open_positions`
   - `sensor.dax_volume_zscore`
   - `sensor.trading_daily_pnl`
   - `sensor.trading_daily_pnl_percent`

4. **Restart Home Assistant:**
   ```bash
   ha core start
   ```

### Option 3: Script to Delete States (SIMPLEST IF HA RESTART NOT DESIRED)

Create a temporary AppDaemon app to delete entity states:

1. **Create `/config/appdaemon/apps/delete_states.py`:**
   ```python
   import appdaemon.plugins.hass.hassapi as hass

   class DeleteStates(hass.Hass):
       def initialize(self):
           entities = [
               "sensor.event_queue_metrics",
               "sensor.nasdaq_volume_zscore",
               "sensor.trading_open_positions",
               "sensor.dax_volume_zscore",
               "sensor.trading_daily_pnl",
               "sensor.trading_daily_pnl_percent"
           ]

           for entity in entities:
               try:
                   # This removes the state from HA
                   self.call_service("homeassistant/remove_entity", entity_id=entity)
                   self.log(f"Deleted: {entity}")
               except Exception as e:
                   self.log(f"Failed to delete {entity}: {e}")
   ```

2. **Add to `apps.yaml`:**
   ```yaml
   delete_states:
     module: delete_states
     class: DeleteStates
   ```

3. **Restart AppDaemon:**
   ```bash
   ha addons restart a0d7b954_appdaemon
   ```

4. **Remove the app after entities are deleted**

### Option 2: Deletion via Home Assistant CLI (ALTERNATIVE)

If you have SSH access to Home Assistant:

```bash
ssh homeassistant

# Delete entities using ha CLI
ha entities delete sensor.event_queue_metrics
ha entities delete sensor.nasdaq_volume_zscore
ha entities delete sensor.trading_open_positions
ha entities delete sensor.dax_volume_zscore
ha entities delete sensor.trading_daily_pnl
ha entities delete sensor.trading_daily_pnl_percent

# Restart AppDaemon
ha addons restart a0d7b954_appdaemon
```

### Option 3: Deletion via REST API (ADVANCED)

If you have a long-lived access token:

```bash
# Set your HA access token
HA_TOKEN="your_token_here"
HA_URL="http://homeassistant.local:8123"

# Delete each entity
curl -X DELETE "$HA_URL/api/states/sensor.event_queue_metrics" \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json"

curl -X DELETE "$HA_URL/api/states/sensor.nasdaq_volume_zscore" \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json"

curl -X DELETE "$HA_URL/api/states/sensor.trading_open_positions" \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json"

curl -X DELETE "$HA_URL/api/states/sensor.dax_volume_zscore" \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json"

curl -X DELETE "$HA_URL/api/states/sensor.trading_daily_pnl" \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json"

curl -X DELETE "$HA_URL/api/states/sensor.trading_daily_pnl_percent" \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json"
```

## Expected Results

After deleting and restarting AppDaemon:

✅ **No more HTTP 400 errors** in logs
✅ **Entities successfully update** with state and attributes
✅ **Dashboard shows correct values** for positions, balance, PnL
✅ **All 6 entities recreated** by AppDaemon on first update

## Verification

After restart, check logs for successful updates:

```bash
tail -f /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log | grep -E "(trading_open_positions|volume_zscore|event_queue|✅)"
```

You should see:
```
[ACCOUNT_MONITOR] ✅ trading_open_positions updated to 0
[ACCOUNT_MONITOR] ✅ trading_daily_pnl_percent updated
```

And NO:
```
ERROR HASS: [400] HTTP POST: Bad Request
```

## Prevention

To prevent entity corruption in future:

1. ✅ **Already implemented:** `replace=True` flag prevents auto-merging
2. ✅ **Already implemented:** Granular try-except blocks prevent cascade failures
3. ⚠️ **TODO:** Add entity validation before set_state() calls
4. ⚠️ **TODO:** Implement entity health check on startup

## Related Issues

- BUGFIX_CONCURRENT_POSITION_CLOSE.md - Previous fix for position count updates
- This is a different issue: not caused by attributes, but by corrupted entity registry

## Technical Details

**Error signature:**
```python
File "/usr/lib/python3.12/site-packages/appdaemon/state.py", line 793, in set_state
    if "entity_id" in result:
       ^^^^^^^^^^^^^^^^^^^^^
TypeError: argument of type 'ClientResponseError' is not iterable
```

**Root cause:** HA API returns HTTP 400 (ClientResponseError), but AppDaemon expects dict with "entity_id" key. This happens when entity is corrupted and HA refuses to update it.

**Testing:**
- ✅ Tested with attributes removed → Still fails
- ✅ Tested with replace=True removed → Still fails
- ✅ Tested with minimal state only → Still fails
- ✅ Conclusion: Entity itself is corrupted, not the update request

## Next Steps

1. ✅ User manually deletes 6 corrupted entities via HA UI
2. ✅ User restarts AppDaemon
3. ⏳ Verify entities recreate successfully
4. ⏳ Monitor logs for 24 hours to ensure no recurrence
5. ⏳ Consider implementing entity health check on startup
