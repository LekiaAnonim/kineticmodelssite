"""
Management command: run PyTeCK simulation for a ChemKED file and post
results back to a GitHub pull request.

Called by the ``pyteck-ci-simulate`` GitHub Actions workflow when a
``repository_dispatch`` event arrives from the ChemKED-database CI.

Usage::

    python manage.py ci_simulate \
        --chemked-yaml /tmp/methane_Smith_2020.yaml \
        --pr-repo LekiaAnonim/ChemKED-database \
        --pr-number 42 \
        --commit-sha abc123def456

Optional flags::

    --model-id 7          # explicit model PK (skip auto-detection)
    --max-models 3        # cap number of auto-detected models
"""

import json
import logging
import os
import tempfile

import requests
import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from analysis.models import (
    FuelModelCompatibility,
    FuelSpecies,
    SimulationRun,
    SimulationResult,
    SimulationStatus,
    TriggerType,
)
from analysis.services.simulation import (
    get_cantera_mechanism_from_model,
    parse_pyteck_results,
    run_pyteck_simulation,
)
from database.models import KineticModel

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Reuse the fuel detection heuristic from the PR service
_NON_FUEL = {
    "oxygen", "o2", "nitrogen", "n2", "argon", "ar", "helium", "he",
    "carbon dioxide", "co2", "water", "h2o", "neon", "ne", "krypton", "kr",
    "nitric oxide", "no", "nitrogen dioxide", "no2", "nitrous oxide", "n2o",
}


def _extract_fuel_from_yaml(filepath):
    """Parse a ChemKED YAML file and return the primary fuel species name."""
    with open(filepath, "r") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return None

    composition = None
    cp = data.get("common-properties", {})
    if isinstance(cp, dict) and "composition" in cp:
        composition = cp["composition"]
    if composition is None:
        dps = data.get("datapoints", [])
        if dps and isinstance(dps[0], dict) and "composition" in dps[0]:
            composition = dps[0]["composition"]
    if not composition or "species" not in composition:
        return None

    best_name, best_amount = None, -1
    for sp in composition["species"]:
        name = sp.get("species-name", "")
        amount_raw = sp.get("amount", [0])
        if isinstance(amount_raw, list):
            amount = float(amount_raw[0]) if amount_raw else 0
        else:
            amount = float(amount_raw)
        if name.lower() in _NON_FUEL:
            continue
        if amount > best_amount:
            best_amount = amount
            best_name = name
    return best_name


def _extract_fuel_smiles_from_yaml(filepath):
    """Parse a ChemKED YAML and return the primary fuel's SMILES & InChI."""
    with open(filepath, "r") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return None, None

    fuel_name = _extract_fuel_from_yaml(filepath)
    if not fuel_name:
        return None, None

    composition = None
    cp = data.get("common-properties", {})
    if isinstance(cp, dict) and "composition" in cp:
        composition = cp["composition"]
    if composition is None:
        dps = data.get("datapoints", [])
        if dps and isinstance(dps[0], dict) and "composition" in dps[0]:
            composition = dps[0]["composition"]
    if not composition or "species" not in composition:
        return None, None

    for sp in composition["species"]:
        if sp.get("species-name", "").lower() == fuel_name.lower():
            smiles = None
            inchi = sp.get("InChI", "")
            # Look for SMILES in the SMILES field
            smiles = sp.get("SMILES", "")
            return smiles or "", inchi or ""
    return None, None


def _find_compatible_models(fuel_name, fuel_smiles, fuel_inchi, max_models=3):
    """Find kinetic models compatible with the given fuel species.

    Queries the precomputed FuelModelCompatibility table first.
    Falls back to name-based search on FuelSpecies if no InChI match.
    """
    models_found = []

    # Try InChI match on FuelSpecies first (most reliable)
    fuel_qs = FuelSpecies.objects.none()
    if fuel_inchi:
        fuel_qs = FuelSpecies.objects.filter(inchi=fuel_inchi)
    if not fuel_qs.exists() and fuel_smiles:
        fuel_qs = FuelSpecies.objects.filter(smiles=fuel_smiles)
    if not fuel_qs.exists() and fuel_name:
        fuel_qs = FuelSpecies.objects.filter(
            common_name__iexact=fuel_name
        ) | FuelSpecies.objects.filter(
            name_variants__contains=[fuel_name]
        )

    for fuel_obj in fuel_qs[:1]:  # Take the first matching FuelSpecies
        compat_qs = (
            FuelModelCompatibility.objects
            .filter(fuel=fuel_obj, is_compatible=True)
            .select_related("kinetic_model")
            .order_by("-kinetic_model__pk")
        )
        for compat in compat_qs[:max_models]:
            models_found.append(compat.kinetic_model)

    return models_found


def _get_experiment_type(filepath):
    """Return the experiment-type from a ChemKED file."""
    with open(filepath, "r") as f:
        data = yaml.safe_load(f)
    return data.get("experiment-type", "").lower().strip()


def _post_github_comment(pr_repo, pr_number, body, token):
    """Post a comment on a GitHub PR."""
    url = f"{GITHUB_API}/repos/{pr_repo}/issues/{pr_number}/comments"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={"body": body},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Failed to post PR comment: {resp.status_code} {resp.text}")
    return resp


def _post_commit_status(pr_repo, commit_sha, state, description, token):
    """Set a commit status on GitHub."""
    url = f"{GITHUB_API}/repos/{pr_repo}/statuses/{commit_sha}"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={
            "state": state,  # "success", "failure", "pending", "error"
            "description": description[:140],
            "context": "PyTeCK Simulation",
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Failed to set commit status: {resp.status_code} {resp.text}")
    return resp


class Command(BaseCommand):
    help = (
        "Run PyTeCK simulation for a ChemKED YAML file and post "
        "results back to a GitHub pull request."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--chemked-yaml",
            required=True,
            help="Path to the ChemKED YAML file to simulate.",
        )
        parser.add_argument(
            "--pr-repo",
            required=True,
            help="GitHub repo in owner/name format (e.g. LekiaAnonim/ChemKED-database).",
        )
        parser.add_argument(
            "--pr-number",
            type=int,
            required=True,
            help="Pull request number.",
        )
        parser.add_argument(
            "--commit-sha",
            required=True,
            help="Commit SHA to set status on.",
        )
        parser.add_argument(
            "--model-id",
            type=int,
            help="Explicit kinetic model PK (skip auto-detection).",
        )
        parser.add_argument(
            "--max-models",
            type=int,
            default=3,
            help="Max number of auto-detected models to simulate against.",
        )
        parser.add_argument(
            "--github-token",
            default="",
            help="GitHub token override (defaults to GITHUB_TOKEN setting).",
        )

    def handle(self, *args, **options):
        chemked_path = options["chemked_yaml"]
        pr_repo = options["pr_repo"]
        pr_number = options["pr_number"]
        commit_sha = options["commit_sha"]
        model_id = options.get("model_id")
        max_models = options["max_models"]
        github_token = options["github_token"] or getattr(settings, "GITHUB_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")

        if not os.path.isfile(chemked_path):
            raise CommandError(f"File not found: {chemked_path}")

        if not github_token:
            raise CommandError(
                "GitHub token required. Set GITHUB_TOKEN env var or use --github-token."
            )

        # Set pending status
        _post_commit_status(
            pr_repo, commit_sha, "pending",
            "PyTeCK simulation in progress...", github_token,
        )

        filename = os.path.basename(chemked_path)
        self.stdout.write(self.style.NOTICE(f"Processing: {filename}"))

        # Check experiment type
        exp_type = _get_experiment_type(chemked_path)
        if exp_type != "ignition delay":
            msg = f"Skipped — experiment type '{exp_type}' is not supported by PyTeCK"
            self.stdout.write(self.style.WARNING(msg))
            _post_commit_status(pr_repo, commit_sha, "success", msg, github_token)
            _post_github_comment(
                pr_repo, pr_number,
                f"### PyTeCK Simulation\n\n⏭️ {msg}\n\n"
                f"Only ignition delay datasets can be simulated.",
                github_token,
            )
            return

        # Find compatible models
        if model_id:
            try:
                models_to_test = [KineticModel.objects.get(pk=model_id)]
            except KineticModel.DoesNotExist:
                raise CommandError(f"KineticModel with pk={model_id} not found.")
            self.stdout.write(f"  Using explicit model: {models_to_test[0].model_name}")
        else:
            fuel_name = _extract_fuel_from_yaml(chemked_path)
            fuel_smiles, fuel_inchi = _extract_fuel_smiles_from_yaml(chemked_path)
            self.stdout.write(
                f"  Fuel: {fuel_name} | SMILES: {fuel_smiles} | InChI: {fuel_inchi}"
            )
            models_to_test = _find_compatible_models(
                fuel_name, fuel_smiles, fuel_inchi, max_models
            )
            if not models_to_test:
                msg = f"No compatible kinetic models found for fuel '{fuel_name}'"
                self.stdout.write(self.style.WARNING(msg))
                _post_commit_status(pr_repo, commit_sha, "success", msg, github_token)
                _post_github_comment(
                    pr_repo, pr_number,
                    f"### PyTeCK Simulation\n\n⚠️ {msg}\n\n"
                    f"No models in the database contain the fuel species "
                    f"**{fuel_name}** (InChI: `{fuel_inchi}`).\n"
                    f"The dataset is valid and can still be merged.",
                    github_token,
                )
                return
            self.stdout.write(
                f"  Found {len(models_to_test)} compatible model(s): "
                + ", ".join(m.model_name for m in models_to_test)
            )

        # We need a temporary ExperimentDataset-like object for the simulation.
        # The CI simulation works with the ChemKED file directly on disk,
        # so we create a lightweight wrapper.
        from chemked_database.models import ExperimentDataset
        temp_dataset = _create_temp_dataset(chemked_path)

        # Run simulations
        results_table = []
        any_failure = False

        for model in models_to_test:
            self.stdout.write(f"  Simulating: {model.model_name}...")
            results_dir = tempfile.mkdtemp(prefix="pyteck_ci_")

            try:
                success, message, results_dict = run_pyteck_simulation(
                    model=model,
                    dataset=temp_dataset,
                    results_dir=results_dir,
                    skip_validation=True,
                )

                # Create SimulationRun record
                run = SimulationRun.objects.create(
                    kinetic_model=model,
                    dataset=temp_dataset,
                    status=SimulationStatus.COMPLETED if success else SimulationStatus.FAILED,
                    triggered_by=TriggerType.API,
                    started_at=timezone.now(),
                    completed_at=timezone.now(),
                    results_dir=results_dir,
                    error_message="" if success else message,
                )

                error_func = None
                num_datapoints = 0
                if success and results_dict:
                    parsed = parse_pyteck_results(results_dict)
                    error_func = parsed.get("average_error_function")
                    for ds in parsed.get("datasets", []):
                        num_datapoints += len(ds.get("datapoints", []))

                    SimulationResult.objects.create(
                        simulation_run=run,
                        average_error_function=error_func,
                        average_deviation_function=parsed.get("average_deviation_function"),
                        results_json=results_dict,
                        num_datapoints=num_datapoints,
                        num_successful=num_datapoints,
                    )
                    run.spec_keys_snapshot = results_dict.get("spec_keys", {})
                    run.save(update_fields=["spec_keys_snapshot"])

                results_table.append({
                    "model_name": model.model_name,
                    "model_pk": model.pk,
                    "success": success,
                    "message": message,
                    "error_function": error_func,
                    "num_datapoints": num_datapoints,
                })

                if success:
                    ef_str = f"{error_func:.4f}" if error_func is not None else "N/A"
                    self.stdout.write(
                        self.style.SUCCESS(f"    ✓ {model.model_name}: E={ef_str}, {num_datapoints} pts")
                    )
                else:
                    any_failure = True
                    self.stdout.write(self.style.ERROR(f"    ✗ {model.model_name}: {message}"))

            except Exception as e:
                logger.exception(f"Unexpected error simulating {model.model_name}")
                any_failure = True
                results_table.append({
                    "model_name": model.model_name,
                    "model_pk": model.pk,
                    "success": False,
                    "message": str(e),
                    "error_function": None,
                    "num_datapoints": 0,
                })

        # Build markdown comment
        comment_body = _build_comment(filename, results_table)

        # Post results
        passed = sum(1 for r in results_table if r["success"])
        total = len(results_table)
        status_state = "success" if not any_failure else "failure"
        status_desc = f"PyTeCK: {passed}/{total} models passed"

        _post_commit_status(pr_repo, commit_sha, status_state, status_desc, github_token)
        _post_github_comment(pr_repo, pr_number, comment_body, github_token)

        self.stdout.write(self.style.SUCCESS(f"\nDone: {status_desc}"))


def _create_temp_dataset(chemked_path):
    """Create an ExperimentDataset record for the CI file.

    The dataset is saved to the DB so that ``run_pyteck_simulation()``
    can load it via ``get_chemked_dataset_path()``.
    """
    from chemked_database.models import ExperimentDataset

    with open(chemked_path, "r") as f:
        data = yaml.safe_load(f)

    filename = os.path.basename(chemked_path)
    short_name = os.path.splitext(filename)[0]
    exp_type = data.get("experiment-type", "ignition delay")

    dataset = ExperimentDataset.objects.create(
        dataset_name=f"CI: {short_name}",
        short_name=short_name,
        experiment_type=exp_type,
        chemked_file_path=os.path.abspath(chemked_path),
    )
    return dataset


def _build_comment(filename, results_table):
    """Build a GitHub PR comment in markdown."""
    lines = [
        "### PyTeCK Simulation Results",
        "",
        f"**File:** `{filename}`",
        "",
        "| Model | Status | Error Function | Datapoints |",
        "|-------|--------|---------------|------------|",
    ]

    for r in results_table:
        status = "✅ Pass" if r["success"] else "❌ Fail"
        ef = f'{r["error_function"]:.4f}' if r["error_function"] is not None else "—"
        pts = r["num_datapoints"] or "—"
        lines.append(f'| {r["model_name"]} | {status} | {ef} | {pts} |')

    if not results_table:
        lines.append("| — | No models tested | — | — |")

    lines.append("")

    # Add failure details
    failures = [r for r in results_table if not r["success"]]
    if failures:
        lines.append("<details><summary>Failure details</summary>\n")
        for r in failures:
            lines.append(f"**{r['model_name']}:** {r['message']}\n")
        lines.append("</details>\n")

    lines.append(
        "*Simulated on [kineticmodelssite](https://github.com/"
        f"{os.getenv('GITHUB_REPO_OWNER', 'LekiaAnonim')}/kineticmodelssite) "
        f"using auto-detected compatible models.*"
    )

    return "\n".join(lines)
