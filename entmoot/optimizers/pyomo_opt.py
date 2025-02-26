from collections import namedtuple
from entmoot import Enting, ProblemConfig
from entmoot.utils import OptResult
import pyomo.environ as pyo


class PyomoOptimizer:
    def __init__(self, problem_config: ProblemConfig, params: dict = None):
        self._params = {} if params is None else params
        self._problem_config = problem_config
        self._curr_sol = None
        self._active_leaves = None

    @property
    def get_curr_sol(self) -> list:
        """
        returns current solution (i.e. optimal points) from optimization run
        """
        assert self._curr_sol is not None, "No solution was generated yet."
        return self._curr_sol

    def get_active_leaf_sol(self) -> list:
        """
        returns current solution (i.e. optimal points) from optimization based
        """
        assert self._curr_sol is not None, "No solution was generated yet."
        return self._active_leaves

    def solve(
        self, tree_model: Enting, model_core: pyo.ConcreteModel = None, weights: tuple = None
    ) -> namedtuple:
        """
        Solves the Pyomo optimization model
        """
        if model_core is None:
            opt_model = self._problem_config.get_pyomo_model_core()
        else:
            # create model copy to not overwrite original one
            opt_model = self._problem_config.copy_pyomo_model_core(model_core)

        # check weights
        if weights is not None:
            assert len(weights) == len(self._problem_config.obj_list), (
                f"Number of 'weights' is '{len(weights)}', number of objectives "
                f"is '{len(self._problem_config.obj_list)}'."
            )
            assert sum(weights) == 1.0, "weights don't add up to 1.0"

        # choose solver
        opt = pyo.SolverFactory(self._params["solver_name"])

        # set solver parameters
        if "solver_options" in self._params:
            for k, v in self._params["solver_options"].items():
                opt.options[k] = v

        # build pyomo model using information from tree model
        tree_model.add_to_pyomo_model(opt_model)

        # Solve optimization model
        opt.solve(opt_model, tee=True)

        # update current solution
        self._curr_sol, self._active_leaves = self._get_sol(opt_model)

        return OptResult(
            self.get_curr_sol,
            pyo.value(opt_model.obj),
            [opt_model._unscaled_mu[k].value for k in opt_model._unscaled_mu],
        )

    def _get_sol(self, solved_model: pyo.ConcreteModel) -> list:
        # extract solutions from conti and discrete variables
        res = []
        for idx, feat in enumerate(self._problem_config.feat_list):
            curr_var = solved_model._all_feat[idx]
            if feat.is_cat():
                # find active category
                sol_cat = [
                    int(round(pyo.value(curr_var[enc_cat])))
                    for enc_cat in feat.enc_cat_list
                ].index(1)
                res.append(sol_cat)
            else:
                res.append(pyo.value(curr_var))

        # extract active leaves of solution
        def obj_leaf_index(model_obj, obj_name):
            # this function is the same as in 'tree_ensemble.py', TODO: put this in a tree_utils?
            for tree in range(model_obj._num_trees(obj_name)):
                for leaf in model_obj._leaves(obj_name, tree):
                    yield tree, leaf

        act_leaves = []
        for idx, obj in enumerate(self._problem_config.obj_list):
            act_leaves.append(
                [(tree_id, leaf_enc) for tree_id, leaf_enc in obj_leaf_index(solved_model, obj.name)
                 if round(pyo.value(solved_model._z[obj.name, tree_id, leaf_enc])) == 1.0])

        return self._problem_config.decode([res]), act_leaves
