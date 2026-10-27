"""Packaged deterministic recipes; never repository or browser supplied scripts."""
from importlib import import_module

# P010-T002 (D142): configuration name → packaged module and the profile its composition must name.
# `django.py` stays byte-identical: its text is part of the fingerprint bound to issued receipts.
RECIPES = {'django': ('my_harness.recipes.django', 'python-django-recipe'),
           'typescript-web': ('my_harness.recipes.typescript_web', 'typescript-web')}
# P011-T020 (D168): `local-config-6` selects the maintained v2 successors (D163) under the same names and profile
# names; `local-config-5` keeps v1. The v1 modules and their profiles stay frozen for issued receipts.
RECIPES_V2 = {'django': ('my_harness.recipes.django_2', 'python-django-recipe'),
              'typescript-web': ('my_harness.recipes.typescript_web_2', 'typescript-web')}
GENERATIONS = {'local-config-5': RECIPES, 'local-config-6': RECIPES_V2, 'local-config-7': RECIPES_V2,
               'local-config-8': RECIPES_V2, 'local-config-9': RECIPES_V2}


def module(name, fmt='local-config-5'):
    return import_module(GENERATIONS[fmt][name][0])


def by_version(version):
    """Configuration name and module of a frozen `project_recipe`, or None for an unknown version."""
    for recipes in GENERATIONS.values():
        for name, (path, _) in recipes.items():
            recipe = import_module(path)
            if recipe.VERSION == version:
                return name, recipe
    return None


def implementation(recipe):
    """What a composition binds of the packaged recipe (D168).

    v1 has one fingerprint. A v2 fingerprint depends on the work language, which the project's SQLite row fixes
    (D167) and the preparation plan seals; the composition binds the implementation for every admitted language."""
    if hasattr(recipe, 'WORK_LANGUAGES'):
        return {'implementation_sha256_by_work_language': {language: recipe.fingerprint(language)
                                                           for language in recipe.WORK_LANGUAGES}}
    return {'implementation_sha256': recipe.fingerprint()}
