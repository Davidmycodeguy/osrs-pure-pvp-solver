//! Exact-duplicate removal and Pareto pruning (port of `pure_solver.candidate_reduction`).
//!
//! Candidates are compared only inside a comparison class (same account, same
//! weapon action set).  Within a class a candidate is removed when another one
//! has a superset of capabilities and is weakly better on every metric and
//! strictly better somewhere.  Survivor sets are order-independent; audits pick
//! the smallest dominator under the Python sort key so reports match exactly.

use std::cmp::Ordering;
use std::collections::HashMap;
use std::sync::Arc;

use rayon::prelude::*;
use serde_json::{json, Value};

/// Frozen `action_class` mapping, fields in the sorted-key order Python freezes them.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ComparisonClass {
    pub account_levels: Vec<(String, i64)>,
    pub attack_styles: Vec<String>,
    pub compatible_ammo_ids: Vec<i64>,
    pub level_band: Vec<(String, i64)>,
    pub mechanic_flags: Vec<String>,
    pub profile_id: i64,
    pub spell_ids: Vec<String>,
    pub two_handed: bool,
    pub weapon_type: String,
}

fn pairs(values: &[(String, i64)]) -> Value {
    Value::Array(values.iter().map(|(k, v)| json!([k, v])).collect())
}

impl ComparisonClass {
    /// `_freeze(action_class)` as canonical JSON: a list of `[key, value]` pairs.
    pub fn frozen_document(&self) -> Value {
        json!([
            ["account_levels", pairs(&self.account_levels)],
            ["attack_styles", self.attack_styles],
            ["compatible_ammo_ids", self.compatible_ammo_ids],
            ["level_band", pairs(&self.level_band)],
            ["mechanic_flags", self.mechanic_flags],
            ["profile_id", self.profile_id],
            ["spell_ids", self.spell_ids],
            ["two_handed", self.two_handed],
            ["weapon_type", self.weapon_type],
        ])
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct ReductionCandidate {
    pub candidate_id: String,
    pub equivalence_signature: String,
    pub comparison_class: Arc<ComparisonClass>,
    /// Sorted by metric name.
    pub metrics: Vec<(String, i64)>,
    /// Sorted, deduplicated capability tokens.
    pub capabilities: Vec<String>,
}

impl ReductionCandidate {
    pub fn metric_names(&self) -> Vec<&str> {
        self.metrics.iter().map(|(name, _)| name.as_str()).collect()
    }

    fn metric_names_owned(&self) -> Vec<String> {
        self.metrics.iter().map(|(name, _)| name.clone()).collect()
    }
}

/// `_candidate_sort_key`: class, metric names, negated metric values, more capabilities first, capabilities, id.
pub fn sort_key_cmp(left: &ReductionCandidate, right: &ReductionCandidate) -> Ordering {
    left.comparison_class
        .cmp(&right.comparison_class)
        .then_with(|| left.metric_names().cmp(&right.metric_names()))
        .then_with(|| {
            for ((_, l), (_, r)) in left.metrics.iter().zip(&right.metrics) {
                match r.cmp(l) {
                    Ordering::Equal => continue,
                    other => return other,
                }
            }
            Ordering::Equal
        })
        .then_with(|| right.capabilities.len().cmp(&left.capabilities.len()))
        .then_with(|| left.capabilities.cmp(&right.capabilities))
        .then_with(|| left.candidate_id.cmp(&right.candidate_id))
}

fn is_superset(left: &[String], right: &[String]) -> bool {
    // Both sorted and deduplicated.
    let mut index = 0;
    for token in right {
        while index < left.len() && left[index] < *token {
            index += 1;
        }
        if index >= left.len() || left[index] != *token {
            return false;
        }
        index += 1;
    }
    true
}

pub fn dominates(left: &ReductionCandidate, right: &ReductionCandidate) -> bool {
    if left.candidate_id == right.candidate_id || left.comparison_class != right.comparison_class || left.metric_names() != right.metric_names() {
        return false;
    }
    if !is_superset(&left.capabilities, &right.capabilities) {
        return false;
    }
    let mut strictly_better = left.capabilities.len() > right.capabilities.len();
    for ((_, l), (_, r)) in left.metrics.iter().zip(&right.metrics) {
        if l < r {
            return false;
        }
        if l > r {
            strictly_better = true;
        }
    }
    strictly_better
}

#[derive(Clone, Debug)]
pub struct ExactDuplicateAudit {
    pub removed_candidate_id: String,
    pub surviving_candidate_id: String,
    pub equivalence_signature: String,
    pub comparison_class: Arc<ComparisonClass>,
}

impl ExactDuplicateAudit {
    pub fn to_document(&self) -> Value {
        json!({
            "removed_candidate_id": self.removed_candidate_id,
            "surviving_candidate_id": self.surviving_candidate_id,
            "equivalence_signature": self.equivalence_signature,
            "comparison_class": self.comparison_class.frozen_document(),
            "reason": "exact combat-equivalent signature",
        })
    }
}

#[derive(Clone, Debug)]
pub struct DominanceAudit {
    pub removed_candidate_id: String,
    pub surviving_candidate_id: String,
    pub comparison_class: Arc<ComparisonClass>,
    pub metric_names: Vec<String>,
    pub removed_capabilities: Vec<String>,
    pub surviving_capabilities: Vec<String>,
}

const DOMINANCE_REASON: &str =
    "same comparison class and metric dimensions; every metric is weakly better; capabilities are a superset; at least one combat dimension is strictly better";

impl DominanceAudit {
    pub fn to_document(&self) -> Value {
        json!({
            "removed_candidate_id": self.removed_candidate_id,
            "surviving_candidate_id": self.surviving_candidate_id,
            "comparison_class": self.comparison_class.frozen_document(),
            "metric_names": self.metric_names,
            "removed_capabilities": self.removed_capabilities,
            "surviving_capabilities": self.surviving_capabilities,
            "reason": DOMINANCE_REASON,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReductionCounts {
    pub starting_candidates: usize,
    pub exact_duplicates_removed: usize,
    pub dominated_candidates_removed: usize,
    pub remaining_pareto_candidates: usize,
}

impl ReductionCounts {
    pub fn to_document(&self) -> serde_json::Map<String, Value> {
        let mut map = serde_json::Map::new();
        map.insert("starting_candidates".into(), json!(self.starting_candidates));
        map.insert("exact_duplicates_removed".into(), json!(self.exact_duplicates_removed));
        map.insert("dominated_candidates_removed".into(), json!(self.dominated_candidates_removed));
        map.insert("remaining_pareto_candidates".into(), json!(self.remaining_pareto_candidates));
        map
    }
}

#[derive(Clone, Debug)]
pub struct CandidateReductionResult {
    pub retained_candidates: Vec<ReductionCandidate>,
    pub exact_duplicate_audits: Vec<ExactDuplicateAudit>,
    pub dominance_audits: Vec<DominanceAudit>,
    pub counts: ReductionCounts,
}

fn audit_order<T>(audits: &mut [T], key: impl Fn(&T) -> (String, String)) {
    audits.sort_by_cached_key(key);
}

/// Candidates sharing (equivalence signature, comparison class, metrics, capabilities) are exact duplicates.
type DuplicateKey = (String, Arc<ComparisonClass>, Vec<(String, i64)>, Vec<String>);

pub fn deduplicate_candidates(candidates: Vec<ReductionCandidate>) -> (Vec<ReductionCandidate>, Vec<ExactDuplicateAudit>) {
    let mut grouped: HashMap<DuplicateKey, Vec<ReductionCandidate>> = HashMap::new();
    for candidate in candidates {
        let key = (
            candidate.equivalence_signature.clone(),
            candidate.comparison_class.clone(),
            candidate.metrics.clone(),
            candidate.capabilities.clone(),
        );
        grouped.entry(key).or_default().push(candidate);
    }
    let mut survivors = Vec::with_capacity(grouped.len());
    let mut audits = Vec::new();
    for (_, mut records) in grouped {
        records.sort_by(sort_key_cmp);
        let survivor = records.remove(0);
        for removed in records {
            audits.push(ExactDuplicateAudit {
                removed_candidate_id: removed.candidate_id,
                surviving_candidate_id: survivor.candidate_id.clone(),
                equivalence_signature: survivor.equivalence_signature.clone(),
                comparison_class: survivor.comparison_class.clone(),
            });
        }
        survivors.push(survivor);
    }
    survivors.sort_by(sort_key_cmp);
    audit_order(&mut audits, |a| (a.surviving_candidate_id.clone(), a.removed_candidate_id.clone()));
    (survivors, audits)
}

fn prune_group(mut ordered: Vec<ReductionCandidate>) -> (Vec<ReductionCandidate>, Vec<DominanceAudit>) {
    ordered.sort_by(sort_key_cmp);
    let mut frontier: Vec<usize> = Vec::new();
    for index in 0..ordered.len() {
        let candidate = &ordered[index];
        if frontier.iter().any(|&other| dominates(&ordered[other], candidate)) {
            continue;
        }
        frontier.retain(|&existing| !dominates(candidate, &ordered[existing]));
        frontier.push(index);
    }
    frontier.sort_unstable();
    let mut audits = Vec::new();
    let mut frontier_cursor = 0;
    for index in 0..ordered.len() {
        if frontier_cursor < frontier.len() && frontier[frontier_cursor] == index {
            frontier_cursor += 1;
            continue;
        }
        let candidate = &ordered[index];
        // `ordered` is sorted by the Python key, so the first frontier dominator is the minimum.
        let dominator = frontier
            .iter()
            .map(|&i| &ordered[i])
            .find(|other| dominates(other, candidate))
            .expect("dominance is transitive");
        audits.push(DominanceAudit {
            removed_candidate_id: candidate.candidate_id.clone(),
            surviving_candidate_id: dominator.candidate_id.clone(),
            comparison_class: candidate.comparison_class.clone(),
            metric_names: candidate.metric_names_owned(),
            removed_capabilities: candidate.capabilities.clone(),
            surviving_capabilities: dominator.capabilities.clone(),
        });
    }
    let survivors = frontier.into_iter().map(|i| ordered[i].clone()).collect();
    (survivors, audits)
}

pub fn pareto_prune_candidates(candidates: Vec<ReductionCandidate>) -> (Vec<ReductionCandidate>, Vec<DominanceAudit>) {
    let mut groups: HashMap<(Arc<ComparisonClass>, Vec<String>), Vec<ReductionCandidate>> = HashMap::new();
    for candidate in candidates {
        let key = (candidate.comparison_class.clone(), candidate.metric_names_owned());
        groups.entry(key).or_default().push(candidate);
    }
    let results: Vec<(Vec<ReductionCandidate>, Vec<DominanceAudit>)> = groups.into_par_iter().map(|(_, group)| prune_group(group)).collect();
    let mut survivors = Vec::new();
    let mut audits = Vec::new();
    for (group_survivors, group_audits) in results {
        survivors.extend(group_survivors);
        audits.extend(group_audits);
    }
    survivors.sort_by(sort_key_cmp);
    audit_order(&mut audits, |a| (a.surviving_candidate_id.clone(), a.removed_candidate_id.clone()));
    (survivors, audits)
}

pub fn reduce_candidates(candidates: Vec<ReductionCandidate>) -> CandidateReductionResult {
    let starting = candidates.len();
    let (deduped, exact_duplicate_audits) = deduplicate_candidates(candidates);
    let (pruned, dominance_audits) = pareto_prune_candidates(deduped);
    let counts = ReductionCounts {
        starting_candidates: starting,
        exact_duplicates_removed: exact_duplicate_audits.len(),
        dominated_candidates_removed: dominance_audits.len(),
        remaining_pareto_candidates: pruned.len(),
    };
    CandidateReductionResult {
        retained_candidates: pruned,
        exact_duplicate_audits,
        dominance_audits,
        counts,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn class() -> Arc<ComparisonClass> {
        Arc::new(ComparisonClass {
            account_levels: vec![("attack".into(), 40)],
            attack_styles: vec!["accurate_stab".into()],
            compatible_ammo_ids: vec![],
            level_band: vec![("attack_min".into(), 40)],
            mechanic_flags: vec![],
            profile_id: 1,
            spell_ids: vec![],
            two_handed: false,
            weapon_type: "sword".into(),
        })
    }

    fn candidate(id: &str, signature: &str, attack: i64, caps: &[&str]) -> ReductionCandidate {
        ReductionCandidate {
            candidate_id: id.into(),
            equivalence_signature: signature.into(),
            comparison_class: class(),
            metrics: vec![("attack_roll".into(), attack), ("max_hit".into(), 5)],
            capabilities: caps.iter().map(|c| c.to_string()).collect(),
        }
    }

    #[test]
    fn duplicates_keep_lowest_id_and_dominance_removes_weaker_rows() {
        let result = reduce_candidates(vec![
            candidate("b", "s1", 100, &["style:accurate_stab"]),
            candidate("a", "s1", 100, &["style:accurate_stab"]),
            candidate("c", "s2", 90, &["style:accurate_stab"]),
            candidate("d", "s3", 90, &["range:at_least:1", "style:accurate_stab"]),
        ]);
        let ids: Vec<&str> = result.retained_candidates.iter().map(|c| c.candidate_id.as_str()).collect();
        assert_eq!(ids, vec!["a", "d"]);
        assert_eq!(result.exact_duplicate_audits[0].removed_candidate_id, "b");
        assert_eq!(result.dominance_audits.len(), 1);
        assert_eq!(result.dominance_audits[0].surviving_candidate_id, "a");
        assert_eq!(result.counts.remaining_pareto_candidates, 2);
    }

    #[test]
    fn frozen_class_document_lists_sorted_pairs() {
        let document = class().frozen_document();
        assert_eq!(document[0][0], "account_levels");
        assert_eq!(document[8][1], "sword");
    }
}
