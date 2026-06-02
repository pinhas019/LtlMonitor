FROM ros:humble

WORKDIR /app

# Install dependencies and compile Spot from source to avoid C++ ABI conflicts
RUN apt-get update && apt-get install -y wget build-essential python3-dev graphviz && \
    wget http://www.lrde.epita.fr/dload/spot/spot-2.12.1.tar.gz && \
    tar -xzf spot-2.12.1.tar.gz && \
    cd spot-2.12.1 && \
    ./configure --prefix=/usr --disable-devel && \
    make -j$(nproc) && \
    make install && \
    cd .. && rm -rf spot-2.12.1* && \
    rm -rf /var/lib/apt/lists/*

# Copy application source
COPY monitor.py main.py ./
COPY formulas.json ./

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/humble/setup.bash && export PYTHONPATH=/usr/lib/python3.10/site-packages:${PYTHONPATH} && python3 main.py \"$@\"", "--"]
