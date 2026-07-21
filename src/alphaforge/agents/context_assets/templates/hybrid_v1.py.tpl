    def compute_scores(self):
        traditional_scores = self.compute_traditional_scores()
        features = self.build_features()
        training_set = self.build_training_set()
        model = self.fit_model(training_set)
        ml_scores = self.predict_scores(model, features)
        return self.combine_scores(traditional_scores, ml_scores)

__REGION_compute_traditional_scores__

__REGION_build_features__

__REGION_build_training_set__

__REGION_fit_model__

__REGION_predict_scores__

__REGION_combine_scores__
