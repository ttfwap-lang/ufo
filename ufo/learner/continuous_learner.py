"""
UFO Continuous Trajectory Learner & Experience Synthesizer

Parses execution traces from completed task sessions in logs/, extracts
successful action chains, records failure patterns, and persists learned
recipes into a local knowledge base to optimize future agent runs.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("UFO_ContinuousLearner")


class ContinuousLearner:
    """
    Harvests past execution logs, turns verified action trajectories into
    reusable macros, and flags problematic controls to eliminate repetitive trial-and-error.
    """

    def __init__(
        self,
        logs_dir: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
        ufo_root: Optional[Union[str, Path]] = None,
    ):
        self.ufo_root = Path(ufo_root) if ufo_root else Path.cwd()
        self.logs_dir = logs_dir or (self.ufo_root / "logs")
        self.memory_dir = memory_dir or (self.ufo_root / "memory")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.recipes_file = self.memory_dir / "learned_recipes.json"
        self.flaky_controls_file = self.memory_dir / "flaky_controls.json"
        self._recipes: Dict[str, Any] = self._load_json(self.recipes_file)
        self._flaky_controls: Dict[str, Any] = self._load_json(self.flaky_controls_file)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")
        return {}

    def _save_json(self, path: Path, data: Dict[str, Any]) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")

    def harvest_all_logs(self) -> Dict[str, int]:
        """Scan logs/ directory and ingest any unparsed completed sessions."""
        if not self.logs_dir.exists():
            return {"processed": 0, "successful": 0, "failed": 0}

        stats = {"processed": 0, "successful": 0, "failed": 0}
        for task_folder in self.logs_dir.iterdir():
            if task_folder.is_dir():
                result_file = task_folder / "result.json"
                if result_file.exists():
                    try:
                        with open(result_file, "r", encoding="utf-8") as f:
                            result_data = json.load(f)
                        stats["processed"] += 1
                        task_id = task_folder.name

                        status = result_data.get("status", "").lower()
                        if status == "success":
                            self._ingest_successful_session(task_id, task_folder, result_data)
                            stats["successful"] += 1
                        else:
                            self._ingest_failed_session(task_id, task_folder, result_data)
                            stats["failed"] += 1
                    except Exception as e:
                        logger.warning(f"Error parsing {result_file}: {e}")

        self._save_json(self.recipes_file, self._recipes)
        self._save_json(self.flaky_controls_file, self._flaky_controls)
        return stats

    def _ingest_successful_session(self, task_id: str, task_folder: Path, result_data: Dict[str, Any]) -> None:
        """Extract steps and actions from a successful run."""
        output_str = str(result_data.get("output", ""))
        output_md = task_folder / "output.md"
        plan_steps = []
        app_name = result_data.get("application", "")

        if output_md.exists():
            try:
                with open(output_md, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                # Parse markdown steps
                for line in content.splitlines():
                    if re.match(r"^### Step \d+", line) or "Executed action" in line:
                        plan_steps.append(line.strip())
            except Exception:
                pass

        # If no markdown steps, parse step_*.json files
        if not plan_steps:
            for step_file in sorted(task_folder.glob("step_*.json")):
                try:
                    with open(step_file, "r", encoding="utf-8") as sf:
                        sdata = json.load(sf)
                    if not app_name and "application" in sdata:
                        app_name = sdata["application"]
                    if "sub_actions" in sdata:
                        for act in sdata["sub_actions"]:
                            plan_steps.append(f"{act.get('action')}: {act.get('control_label', '')} -> {act.get('value', '')}")
                    elif "action" in sdata:
                        plan_steps.append(f"{sdata.get('action')}: {sdata.get('control_label', '')}")
                except Exception:
                    pass

        recipe_key = task_id
        self._recipes[recipe_key] = {
            "task_id": task_id,
            "status": "success",
            "app": app_name,
            "output_summary": output_str[:300],
            "step_count": len(plan_steps),
            "steps": plan_steps[:20],
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }

    def _ingest_failed_session(self, task_id: str, task_folder: Path, result_data: Dict[str, Any]) -> None:
        """Record error patterns and failing controls."""
        error_type = result_data.get("error_type", "UnknownError")
        error_msg = str(result_data.get("error_message", ""))
        
        self._flaky_controls[task_id] = {
            "task_id": task_id,
            "error_type": error_type,
            "error_message": error_msg[:300],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

    def query_recipe(self, query: str) -> Optional[Dict[str, Any]]:
        """Find a previously learned execution recipe matching the query string."""
        query_terms = set(re.findall(r"\w+", query.lower()))
        best_match = None
        highest_score = 0

        for key, rec in self._recipes.items():
            text = (rec.get("task_id", "") + " " + rec.get("output_summary", "") + " " + rec.get("app", "")).lower()
            overlap = sum(1 for term in query_terms if term in text)
            if overlap > highest_score and overlap >= 1:
                highest_score = overlap
                best_match = rec

        return best_match

    def find_recipes_for_task(self, task_name: str, app_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search and return all matching learned recipes for a given task and application."""
        terms = set(re.findall(r"\w+", task_name.lower()))
        if app_name:
            terms.add(app_name.lower())
            
        matches = []
        for rec in self._recipes.values():
            text = (rec.get("task_id", "") + " " + rec.get("output_summary", "") + " " + rec.get("app", "")).lower()
            overlap = sum(1 for term in terms if term in text)
            if overlap > 0:
                matches.append(rec)
        return matches


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    learner = ContinuousLearner()
    stats = learner.harvest_all_logs()
    print("Continuous Learner Log Harvesting Summary:")
    print(json.dumps(stats, indent=2))
    print(f"Total verified recipes learned: {len(learner._recipes)}")
    print(f"Total failure patterns recorded: {len(learner._flaky_controls)}")
