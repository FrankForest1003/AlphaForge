    def compute_scores(self):
        features = self.build_features()
        training_set = self.build_training_set()
        model = self.fit_model(training_set)
        return self.predict_scores(model, features)

__REGION_build_features__

__REGION_build_training_set__

__REGION_fit_model__

__REGION_predict_scores__
