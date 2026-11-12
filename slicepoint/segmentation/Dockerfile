FROM pytorch/pytorch:2.14.1-cuda12.6-cudnn9-runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TOTALSEG_HOME_DIR=/models/totalsegmentator
COPY pyproject.toml ./
COPY slicepoint_model ./slicepoint_model
RUN pip install --no-cache-dir '.[model]' && pip freeze > /app/installed-versions.txt
EXPOSE 8000
CMD ["uvicorn", "slicepoint_model.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
