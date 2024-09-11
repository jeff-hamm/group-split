FROM python:3.11
COPY setup/requirements.txt .
RUN pip install -r ./requirements.txt
COPY src/groupsplit.py .
COPY setup/csv_settings.pkl /
ENTRYPOINT ["python3","groupsplit.py"]