use std::hint::black_box;
use std::time::Duration;

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use lacuna_core::{bootstrap_means, grouped_rank_ic, interval_purge};

fn small_f64(value: usize) -> f64 {
    f64::from(u32::try_from(value).expect("benchmark value fits in u32"))
}

fn index_i64(value: usize) -> i64 {
    i64::try_from(value).expect("benchmark index fits in i64")
}

fn grouped_rank_inputs(rows: usize, group_size: usize) -> (Vec<f64>, Vec<f64>, Vec<usize>) {
    let signal: Vec<f64> = (0..rows).map(|index| small_f64(index % 97)).collect();
    let labels: Vec<f64> = (0..rows)
        .map(|index| small_f64(index * 31 % 101).sin())
        .collect();
    let mut offsets: Vec<usize> = (0..=rows / group_size)
        .map(|group| group * group_size)
        .collect();
    if offsets.last() != Some(&rows) {
        offsets.push(rows);
    }
    (signal, labels, offsets)
}

fn benchmark_grouped_rank_ic(criterion: &mut Criterion) {
    let mut group = criterion.benchmark_group("grouped_rank_ic");
    for rows in [10_000_usize, 100_000] {
        let (signal, labels, offsets) = grouped_rank_inputs(rows, 500);
        group.throughput(Throughput::Elements(rows as u64));
        group.bench_with_input(BenchmarkId::from_parameter(rows), &rows, |bencher, _| {
            bencher.iter(|| {
                grouped_rank_ic(black_box(&signal), black_box(&labels), black_box(&offsets))
                    .expect("benchmark fixture is valid")
            });
        });
    }
    group.finish();
}

fn bootstrap_inputs(sample_size: usize, resamples: usize) -> (Vec<f64>, Vec<usize>, Vec<usize>) {
    let values: Vec<f64> = (0..sample_size)
        .map(|index| (small_f64(index) * 0.017).sin())
        .collect();
    let indices: Vec<usize> = (0..resamples)
        .flat_map(|replicate| {
            (0..sample_size).map(move |index| (replicate * 17 + index * 31) % sample_size)
        })
        .collect();
    let offsets: Vec<usize> = (0..=resamples)
        .map(|replicate| replicate * sample_size)
        .collect();
    (values, indices, offsets)
}

fn benchmark_bootstrap_means(criterion: &mut Criterion) {
    let sample_size = 1_000;
    let resamples = 200;
    let (values, indices, offsets) = bootstrap_inputs(sample_size, resamples);
    let mut group = criterion.benchmark_group("bootstrap_means");
    group.throughput(Throughput::Elements((sample_size * resamples) as u64));
    group.bench_function("1000x200", |bencher| {
        bencher.iter(|| {
            bootstrap_means(black_box(&values), black_box(&indices), black_box(&offsets))
                .expect("benchmark fixture is valid")
        });
    });
    group.finish();
}

fn purge_inputs(train_count: usize, test_count: usize) -> (Vec<i64>, Vec<i64>, Vec<i64>, Vec<i64>) {
    let train_starts: Vec<i64> = (0..train_count).map(index_i64).collect();
    let train_ends: Vec<i64> = train_starts
        .iter()
        .map(|start| start + 1 + start % 20)
        .collect();
    let stride = train_count / test_count;
    let test_starts: Vec<i64> = (0..test_count)
        .map(|index| index_i64(index * stride))
        .collect();
    let test_ends: Vec<i64> = test_starts.iter().map(|start| start + 10).collect();
    (train_starts, train_ends, test_starts, test_ends)
}

fn benchmark_interval_purge(criterion: &mut Criterion) {
    let train_count = 100_000;
    let (train_starts, train_ends, test_starts, test_ends) = purge_inputs(train_count, 1_000);
    let mut group = criterion.benchmark_group("interval_purge");
    group.throughput(Throughput::Elements(train_count as u64));
    group.bench_function("100000x1000", |bencher| {
        bencher.iter(|| {
            interval_purge(
                black_box(&train_starts),
                black_box(&train_ends),
                black_box(&test_starts),
                black_box(&test_ends),
            )
            .expect("benchmark fixture is valid")
        });
    });
    group.finish();
}

fn benchmark_config() -> Criterion {
    Criterion::default()
        .sample_size(10)
        .warm_up_time(Duration::from_millis(250))
        .measurement_time(Duration::from_secs(1))
}

criterion_group! {
    name = benches;
    config = benchmark_config();
    targets = benchmark_grouped_rank_ic, benchmark_bootstrap_means, benchmark_interval_purge
}
criterion_main!(benches);
