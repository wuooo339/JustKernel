import assert from "node:assert/strict";
import test from "node:test";

import { DEMO_EVENTS, DEMO_META, DEMO_STATE } from "../../src/justkernel/web/demo/fixture.js";
import { renderCandidates, renderClusterPage } from "../../src/justkernel/web/views/index.js";

test("demo fixture is synthetic and uses no models/devices", () => {
  assert.equal(DEMO_META.mode, "demo");
  assert.equal(DEMO_META.source, "synthetic");
  assert.equal(DEMO_META.model_calls, 0);
  assert.equal(DEMO_META.device_calls, 0);
  assert.equal(DEMO_EVENTS.length, 17);
});

test("demo replay reaches completed, valid best and visible failure", () => {
  assert.equal(DEMO_STATE.clusters["demo-cluster"].state, "COMPLETED");
  assert.equal(DEMO_STATE.clusters["demo-cluster"].best_candidate_id, "demo-candidate-2");
  assert.equal(DEMO_STATE.candidates["demo-candidate-1"].evaluation.status, "UNTESTED");
  assert.equal(DEMO_STATE.records["demo-record-1"].outcome, "FAIL");
  assert.match(renderCandidates(DEMO_STATE, "demo-cluster"), /data-candidate-state="FAIL"/);
  assert.match(renderClusterPage(DEMO_STATE, "demo-cluster"), /data-best="validated"/);
});
