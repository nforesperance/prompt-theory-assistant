# Eval all 3 theories
python eval.py

# Eval one theory
python eval.py --theories constructivism

# Use claude as agent, openai as judge
python eval.py -p claude --judge-provider openai

# Run just one scenario
python eval.py --scenarios wrong_answer demand_answer
